"""Provider registry — manages AI provider configs, API keys, and model lists.

Stores provider configurations in data/providers.json with encrypted API keys.
Provides a resolution layer so config.yaml can reference aliases instead of
raw model IDs.
"""

import json
import logging
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import anthropic
import openai
import requests
from pydantic import BaseModel

from src.encryption import encrypt, decrypt
from src.openai_adapter import OpenAIAdapter

log = logging.getLogger(__name__)


_DEFAULT_MODELS_URLS = {
    "anthropic": "https://api.anthropic.com/v1/models",
    "openai": "https://api.openai.com/v1/models",
}

APP_USER_AGENT = "NarrativeOrchestrator/1.0"


class ProviderOptions(BaseModel):
    """Provider-specific tuning knobs. All optional — sensible defaults applied.

    These can be set in build/data/providers.json per provider, or will be
    auto-detected from the provider type / model name when possible.

    Sampling parameters:
        temperature:        Randomness (0.0 - 2.0). None = provider default.
        top_p:              Nucleus sampling. None = provider default.
        top_k:              Top-k sampling (not all providers). None = provider default.
        frequency_penalty:  Penalize repeated tokens. None = provider default.
        presence_penalty:   Penalize tokens already present. None = provider default.
        repetition_penalty: Combined repetition penalty (some providers). None = default.
        min_p:              Minimum probability cutoff (some providers). None = default.
        seed:               Deterministic sampling seed. None = non-deterministic.

    Provider quirks:
        reasoning_content:  Add empty reasoning_content field to assistant messages
                            with tool calls. Required by DeepSeek reasoner models.
                            "auto" = detect from model name, true/false = force.
        strip_empty_required: Remove empty 'required' arrays from tool schemas.
                            DeepSeek rejects them. "auto" = detect, true/false = force.
        extra_body:         Arbitrary extra fields merged into the request body.
                            Use for provider-specific params not covered above
                            (e.g. {"reasoning": {"effort": "high"}}).
    """
    # Sampling
    temperature: float | None = None
    top_p: float | None = None
    top_k: int | None = None
    frequency_penalty: float | None = None
    presence_penalty: float | None = None
    repetition_penalty: float | None = None
    min_p: float | None = None
    seed: int | None = None

    # Provider quirks
    reasoning_content: bool | str = "auto"   # "auto", true, false
    strip_empty_required: bool | str = "auto"
    extra_body: dict | None = None


class ProviderConfig(BaseModel):
    alias: str
    name: str
    type: Literal["anthropic", "openai"]
    base_url: str | None = None
    models_url: str | None = None  # Custom URL for fetching model list
    api_key_encrypted: str | None = None
    selected_model: str = ""
    options: ProviderOptions = ProviderOptions()


class ProviderRegistry:
    """Loads provider configs, resolves aliases to configured API clients."""

    def __init__(self, data_dir: Path, user_agent: str = APP_USER_AGENT):
        self.data_dir = data_dir
        self.user_agent = user_agent
        self.providers: dict[str, ProviderConfig] = {}
        self._models_cache: dict[str, list[str]] = {}
        self.load()

    @property
    def _config_path(self) -> Path:
        return self.data_dir / "providers.json"

    @property
    def _cache_path(self) -> Path:
        return self.data_dir / "models-cache.json"

    # ── Persistence ──────────────────────────────────────────────────

    def load(self):
        """Load providers from disk. Auto-creates from env vars if missing."""
        self.data_dir.mkdir(parents=True, exist_ok=True)

        if self._config_path.exists():
            raw = json.loads(self._config_path.read_text(encoding="utf-8"))
            for entry in raw.get("providers", []):
                p = ProviderConfig(**entry)
                self.providers[p.alias] = p
            log.info("Loaded %d provider(s) from %s", len(self.providers), self._config_path)
        else:
            self._bootstrap_from_env()

        # Load models cache
        if self._cache_path.exists():
            try:
                self._models_cache = json.loads(self._cache_path.read_text(encoding="utf-8"))
            except Exception:
                self._models_cache = {}

    def _bootstrap_from_env(self):
        """Create default provider from ANTHROPIC_API_KEY env var."""
        api_key = os.environ.get("ANTHROPIC_API_KEY")
        if api_key:
            encrypted = encrypt(api_key, self.data_dir)
            self.providers["claude"] = ProviderConfig(
                alias="claude",
                name="Anthropic",
                type="anthropic",
                api_key_encrypted=encrypted,
                selected_model="claude-sonnet-4-6",
            )
            self.save()
            log.info("Bootstrapped default 'claude' provider from ANTHROPIC_API_KEY")

    def save(self):
        """Write current provider configs to disk."""
        self.data_dir.mkdir(parents=True, exist_ok=True)
        data = {
            "providers": [p.model_dump() for p in self.providers.values()],
        }
        self._config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _save_models_cache(self):
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self._cache_path.write_text(json.dumps(self._models_cache, indent=2), encoding="utf-8")

    # ── CRUD ─────────────────────────────────────────────────────────

    def add(self, alias: str, name: str, ptype: str, base_url: str | None,
            api_key: str | None, selected_model: str,
            models_url: str | None = None,
            options: dict | None = None) -> ProviderConfig:
        """Add a new provider config."""
        if alias in self.providers:
            raise ValueError(f"Provider alias '{alias}' already exists")

        encrypted = encrypt(api_key, self.data_dir) if api_key else None
        p = ProviderConfig(
            alias=alias,
            name=name,
            type=ptype,  # type: ignore[arg-type]
            base_url=base_url or None,
            models_url=models_url or None,
            api_key_encrypted=encrypted,
            selected_model=selected_model,
            options=ProviderOptions(**(options or {})),
        )
        self.providers[alias] = p
        self.save()
        return p

    def update(self, alias: str, **kwargs: Any) -> ProviderConfig:
        """Update fields on an existing provider."""
        if alias not in self.providers:
            raise KeyError(f"Provider '{alias}' not found")

        p = self.providers[alias]

        if "api_key" in kwargs:
            key = kwargs.pop("api_key")
            if key:
                p.api_key_encrypted = encrypt(key, self.data_dir)

        # Options are merged, not replaced
        if "options" in kwargs:
            opts_dict = kwargs.pop("options")
            if isinstance(opts_dict, dict):
                current = p.options.model_dump()
                current.update(opts_dict)
                p.options = ProviderOptions(**current)

        for field, value in kwargs.items():
            if hasattr(p, field):
                setattr(p, field, value)

        self.save()
        return p

    def remove(self, alias: str):
        """Delete a provider config."""
        if alias not in self.providers:
            raise KeyError(f"Provider '{alias}' not found")
        del self.providers[alias]
        self.save()

    def list_providers(self) -> list[dict]:
        """Return provider list with keys masked for the frontend."""
        result = []
        for p in self.providers.values():
            # Only include non-default options to keep the response clean
            opts = {k: v for k, v in p.options.model_dump().items()
                    if v is not None and v != "auto"}
            result.append({
                "alias": p.alias,
                "name": p.name,
                "type": p.type,
                "base_url": p.base_url,
                "models_url": p.models_url or _default_models_url(p.type, p.base_url),
                "selected_model": p.selected_model,
                "api_key_set": p.api_key_encrypted is not None,
                "options": opts if opts else None,
            })
        return result

    # ── Resolution ───────────────────────────────────────────────────

    def _decrypt_key(self, provider: ProviderConfig) -> str | None:
        """Decrypt the API key for a provider."""
        if provider.api_key_encrypted is None:
            return None
        return decrypt(provider.api_key_encrypted, self.data_dir)

    def get_client(self, alias: str) -> anthropic.Anthropic | OpenAIAdapter:
        """Return a configured API client for the given alias.

        For OpenAI-type providers, returns an OpenAIAdapter that presents
        the same .messages.create() interface as anthropic.Anthropic, so
        agents work unchanged regardless of provider type.
        """
        if alias not in self.providers:
            # Fallback: maybe alias is a raw model ID — use default Anthropic
            log.warning("No provider for alias '%s', falling back to env-based Anthropic client", alias)
            return anthropic.Anthropic(
                default_headers={"User-Agent": self.user_agent},
            )

        p = self.providers[alias]
        api_key = self._decrypt_key(p)

        if p.type == "anthropic":
            kwargs: dict[str, Any] = {
                "default_headers": {"User-Agent": self.user_agent},
            }
            if api_key:
                kwargs["api_key"] = api_key
            if p.base_url:
                kwargs["base_url"] = p.base_url
            return anthropic.Anthropic(**kwargs)
        else:
            kwargs: dict[str, Any] = {
                "default_headers": {"User-Agent": self.user_agent},
            }
            if api_key:
                kwargs["api_key"] = api_key
            else:
                kwargs["api_key"] = "not-needed"  # Some local endpoints don't need a key
            if p.base_url:
                kwargs["base_url"] = p.base_url
            return OpenAIAdapter(openai.OpenAI(**kwargs), options=p.options)

    def get_model(self, alias: str) -> str:
        """Return the selected model ID for an alias."""
        if alias in self.providers:
            return self.providers[alias].selected_model
        # Fallback: treat the alias as a literal model ID
        return alias

    def get_provider_type(self, alias: str) -> str:
        """Return 'anthropic' or 'openai' for the alias."""
        if alias in self.providers:
            return self.providers[alias].type
        return "anthropic"

    # ── Model fetching ───────────────────────────────────────────────

    def fetch_models(self, alias: str) -> list[str]:
        """Fetch models from a configured provider and cache them."""
        if alias not in self.providers:
            raise KeyError(f"Provider '{alias}' not found")

        p = self.providers[alias]
        api_key = self._decrypt_key(p)
        models = _fetch_models(p.type, api_key, p.base_url, p.models_url, self.user_agent)

        self._models_cache[alias] = {
            "models": models,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_models_cache()
        return models

    def fetch_models_adhoc(self, ptype: str, api_key: str | None,
                           base_url: str | None, models_url: str | None = None) -> list[str]:
        """Fetch models without a saved provider (for the 'new provider' form)."""
        return _fetch_models(ptype, api_key, base_url, models_url, self.user_agent)

    def get_cached_models(self, alias: str) -> list[str]:
        """Return cached models for an alias, or empty if none."""
        entry = self._models_cache.get(alias)
        if entry and isinstance(entry, dict):
            return entry.get("models", [])
        return []


def _default_models_url(ptype: str, base_url: str | None) -> str:
    """Build the default models URL from provider type and base URL."""
    if base_url:
        return base_url.rstrip("/") + "/v1/models" if "/v1" not in base_url else base_url.rstrip("/") + "/models"
    return _DEFAULT_MODELS_URLS.get(ptype, "https://api.openai.com/v1/models")


def _fetch_models(ptype: str, api_key: str | None, base_url: str | None,
                  models_url: str | None = None,
                  user_agent: str = APP_USER_AGENT) -> list[str]:
    """Fetch model list from a provider API."""
    url = models_url or _default_models_url(ptype, base_url)

    try:
        headers = {"User-Agent": user_agent}

        if ptype == "anthropic":
            headers["anthropic-version"] = "2023-06-01"
            if api_key:
                headers["x-api-key"] = api_key
        else:
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"

        resp = requests.get(url, headers=headers, timeout=15)
        resp.raise_for_status()
        data = resp.json()
        return sorted(m["id"] for m in data.get("data", []))
    except Exception as e:
        log.error("Failed to fetch models from %s: %s", url, e)
        raise
