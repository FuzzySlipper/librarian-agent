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

log = logging.getLogger(__name__)


class ProviderConfig(BaseModel):
    alias: str
    name: str
    type: Literal["anthropic", "openai"]
    base_url: str | None = None
    api_key_encrypted: str | None = None
    selected_model: str = ""


class ProviderRegistry:
    """Loads provider configs, resolves aliases to configured API clients."""

    def __init__(self, data_dir: Path):
        self.data_dir = data_dir
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
            api_key: str | None, selected_model: str) -> ProviderConfig:
        """Add a new provider config."""
        if alias in self.providers:
            raise ValueError(f"Provider alias '{alias}' already exists")

        encrypted = encrypt(api_key, self.data_dir) if api_key else None
        p = ProviderConfig(
            alias=alias,
            name=name,
            type=ptype,  # type: ignore[arg-type]
            base_url=base_url or None,
            api_key_encrypted=encrypted,
            selected_model=selected_model,
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
            result.append({
                "alias": p.alias,
                "name": p.name,
                "type": p.type,
                "base_url": p.base_url,
                "selected_model": p.selected_model,
                "api_key_set": p.api_key_encrypted is not None,
            })
        return result

    # ── Resolution ───────────────────────────────────────────────────

    def _decrypt_key(self, provider: ProviderConfig) -> str | None:
        """Decrypt the API key for a provider."""
        if provider.api_key_encrypted is None:
            return None
        return decrypt(provider.api_key_encrypted, self.data_dir)

    def get_client(self, alias: str) -> anthropic.Anthropic | openai.OpenAI:
        """Return a configured API client for the given alias."""
        if alias not in self.providers:
            # Fallback: maybe alias is a raw model ID — use default Anthropic
            log.warning("No provider for alias '%s', falling back to env-based Anthropic client", alias)
            return anthropic.Anthropic()

        p = self.providers[alias]
        api_key = self._decrypt_key(p)

        if p.type == "anthropic":
            kwargs: dict[str, Any] = {}
            if api_key:
                kwargs["api_key"] = api_key
            if p.base_url:
                kwargs["base_url"] = p.base_url
            return anthropic.Anthropic(**kwargs)
        else:
            kwargs = {}
            if api_key:
                kwargs["api_key"] = api_key
            else:
                kwargs["api_key"] = "not-needed"  # Some local endpoints don't need a key
            if p.base_url:
                kwargs["base_url"] = p.base_url
            return openai.OpenAI(**kwargs)

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
        models = _fetch_models(p.type, api_key, p.base_url)

        self._models_cache[alias] = {
            "models": models,
            "fetched_at": datetime.now(timezone.utc).isoformat(),
        }
        self._save_models_cache()
        return models

    def fetch_models_adhoc(self, ptype: str, api_key: str | None,
                           base_url: str | None) -> list[str]:
        """Fetch models without a saved provider (for the 'new provider' form)."""
        return _fetch_models(ptype, api_key, base_url)

    def get_cached_models(self, alias: str) -> list[str]:
        """Return cached models for an alias, or empty if none."""
        entry = self._models_cache.get(alias)
        if entry and isinstance(entry, dict):
            return entry.get("models", [])
        return []


def _fetch_models(ptype: str, api_key: str | None, base_url: str | None) -> list[str]:
    """Fetch model list from a provider API."""
    try:
        if ptype == "anthropic":
            url = (base_url or "https://api.anthropic.com") + "/v1/models"
            headers = {"anthropic-version": "2023-06-01"}
            if api_key:
                headers["x-api-key"] = api_key
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []))
        else:
            url = (base_url or "https://api.openai.com/v1").rstrip("/")
            if not url.endswith("/models"):
                url += "/models"
            headers = {}
            if api_key:
                headers["Authorization"] = f"Bearer {api_key}"
            resp = requests.get(url, headers=headers, timeout=15)
            resp.raise_for_status()
            data = resp.json()
            return sorted(m["id"] for m in data.get("data", []))
    except Exception as e:
        log.error("Failed to fetch models: %s", e)
        raise
