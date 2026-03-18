"""Text-to-speech service with provider fallback chain.

Configured via .env:
    TTS_PROVIDERS=browser,openai||sk-xxx

Provider format: type|base_url|api_key  (comma-separated for multiple)
Providers are tried in order; first success wins.

Supported provider types:
    - browser:      Handled client-side via Web Speech API (no backend call needed).
                    Include in chain as a signal to the frontend. The backend skips it.
    - openai:       OpenAI TTS API (also covers compatible services).
    - elevenlabs:   ElevenLabs TTS API.

Additional .env config:
    TTS_VOICE=alloy             Voice name (provider-specific)
    TTS_MODEL=tts-1             Model name (provider-specific)
"""

import logging
import os
from dataclasses import dataclass

import requests

log = logging.getLogger(__name__)


@dataclass
class TTSProvider:
    """A single TTS provider."""
    type: str         # "browser", "openai", "elevenlabs"
    base_url: str = ""
    api_key: str = ""


@dataclass
class TTSResult:
    """Result from a TTS generation request."""
    success: bool
    audio_data: bytes | None = None
    content_type: str = "audio/mpeg"
    error: str | None = None
    provider: str = ""


def parse_providers() -> list[TTSProvider]:
    """Parse TTS_PROVIDERS from environment.

    Format: type|base_url|api_key,type|base_url|api_key,...
    Examples:
        browser
        openai||sk-xxx
        elevenlabs|https://api.elevenlabs.io/v1|xi-xxx
    """
    raw = os.environ.get("TTS_PROVIDERS", "").strip()
    if not raw:
        return []

    providers = []
    for entry in raw.split(","):
        entry = entry.strip()
        if not entry:
            continue
        parts = entry.split("|")
        ptype = parts[0].strip().lower()
        base_url = parts[1].strip() if len(parts) > 1 else ""
        api_key = parts[2].strip() if len(parts) > 2 else ""
        providers.append(TTSProvider(type=ptype, base_url=base_url, api_key=api_key))

    return providers


def get_provider_list() -> list[str]:
    """Get the list of configured provider type names (for the frontend to know what's available)."""
    return [p.type for p in parse_providers()]


# ── OpenAI-compatible TTS ─────────────────────────────────────────────

def _generate_openai(text: str, provider: TTSProvider) -> TTSResult:
    """Generate audio via OpenAI-compatible TTS API."""
    base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
    api_key = provider.api_key or os.environ.get("OPENAI_API_KEY", "")
    voice = os.environ.get("TTS_VOICE", "alloy")
    model = os.environ.get("TTS_MODEL", "tts-1")

    if not api_key:
        return TTSResult(success=False, error="No API key for OpenAI TTS", provider="openai")

    try:
        resp = requests.post(
            f"{base}/audio/speech",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "input": text,
                "voice": voice,
            },
            timeout=60,
        )
        resp.raise_for_status()

        return TTSResult(
            success=True,
            audio_data=resp.content,
            content_type=resp.headers.get("Content-Type", "audio/mpeg"),
            provider="openai",
        )
    except requests.ConnectionError:
        return TTSResult(success=False, error=f"Cannot connect to TTS API at {base}", provider="openai")
    except Exception as e:
        return TTSResult(success=False, error=f"OpenAI TTS error: {e}", provider="openai")


# ── ElevenLabs TTS ────────────────────────────────────────────────────

def _generate_elevenlabs(text: str, provider: TTSProvider) -> TTSResult:
    """Generate audio via ElevenLabs TTS API."""
    base = (provider.base_url or "https://api.elevenlabs.io/v1").rstrip("/")
    api_key = provider.api_key or os.environ.get("ELEVENLABS_API_KEY", "")
    voice = os.environ.get("TTS_VOICE", "21m00Tcm4TlvDq8ikWAM")  # Rachel default

    if not api_key:
        return TTSResult(success=False, error="No API key for ElevenLabs TTS", provider="elevenlabs")

    try:
        resp = requests.post(
            f"{base}/text-to-speech/{voice}",
            headers={
                "xi-api-key": api_key,
                "Content-Type": "application/json",
            },
            json={
                "text": text,
                "model_id": os.environ.get("TTS_MODEL", "eleven_monolingual_v1"),
            },
            timeout=60,
        )
        resp.raise_for_status()

        return TTSResult(
            success=True,
            audio_data=resp.content,
            content_type="audio/mpeg",
            provider="elevenlabs",
        )
    except requests.ConnectionError:
        return TTSResult(success=False, error=f"Cannot connect to ElevenLabs at {base}", provider="elevenlabs")
    except Exception as e:
        return TTSResult(success=False, error=f"ElevenLabs TTS error: {e}", provider="elevenlabs")


# ── Provider registry ────────────────────────────────────────────────

_GENERATORS = {
    "openai": _generate_openai,
    "elevenlabs": _generate_elevenlabs,
    # "browser" is handled client-side — no backend generator needed
}


# ── Public API ────────────────────────────────────────────────────────

def generate_speech(text: str) -> TTSResult:
    """Generate speech audio, trying each configured provider in order.

    Skips 'browser' providers (handled client-side).
    Falls through the chain until one succeeds or all fail.
    """
    providers = parse_providers()

    # Filter out browser-only providers
    server_providers = [p for p in providers if p.type != "browser"]

    if not server_providers:
        return TTSResult(
            success=False,
            error="No server-side TTS providers configured.",
        )

    errors = []
    for provider in server_providers:
        gen_fn = _GENERATORS.get(provider.type)
        if not gen_fn:
            errors.append(f"Unknown TTS provider type: {provider.type}")
            continue

        log.info("Trying TTS provider: %s (%s)", provider.type, provider.base_url or "default")
        result = gen_fn(text, provider)

        if result.success:
            return result

        log.warning("TTS provider %s failed: %s", provider.type, result.error)
        errors.append(f"{provider.type}: {result.error}")

    return TTSResult(
        success=False,
        error="All TTS providers failed:\n" + "\n".join(f"  - {e}" for e in errors),
    )
