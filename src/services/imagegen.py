"""Image generation service with provider fallback chain.

Configured via .env:
    IMAGE_PROVIDERS=comfyui|http://localhost:8188,openai||sk-xxx

Provider format: type|base_url|api_key (url and key optional depending on type)
Providers are tried in order; first success wins.

Supported provider types:
    - comfyui:  Local ComfyUI instance. Uses a workflow template file.
    - openai:   OpenAI images API (also covers DALL-E, any compatible service).

ComfyUI uses whatever checkpoint/sampler/settings are configured in the
workflow template. To customize, edit the workflow JSON — don't try to
expose ComfyUI's full config surface through env vars.
"""

import json
import logging
import os
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path

import requests

log = logging.getLogger(__name__)

# Where generated images get saved
OUTPUT_DIR = Path("generated-images")


@dataclass
class ImageGenResult:
    """Result from an image generation request."""
    success: bool
    image_url: str | None = None
    image_path: str | None = None
    error: str | None = None
    prompt: str = ""
    provider: str = ""


@dataclass
class ImageProvider:
    """A single image generation provider."""
    type: str         # "comfyui" or "openai"
    base_url: str = ""
    api_key: str = ""


def _parse_providers() -> list[ImageProvider]:
    """Parse IMAGE_PROVIDERS from environment.

    Format: type|base_url|api_key,type|base_url|api_key,...
    Examples:
        comfyui|http://localhost:8188
        openai||sk-xxx
        openai|https://api.openai.com/v1|sk-xxx
    """
    raw = os.environ.get("IMAGE_PROVIDERS", "").strip()
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
        providers.append(ImageProvider(type=ptype, base_url=base_url, api_key=api_key))

    return providers


# ── ComfyUI provider ─────────────────────────────────────────────────

# Default workflow template path (sits next to council/, persona/, etc.)
COMFYUI_WORKFLOW_PATH = Path("comfyui-workflow.json")

# Minimal default workflow — basic txt2img using whatever checkpoint
# is loaded in ComfyUI. This gets used if no workflow file exists.
_DEFAULT_COMFYUI_WORKFLOW = {
    "3": {
        "class_type": "KSampler",
        "inputs": {
            "seed": -1,
            "steps": 20,
            "cfg": 7.0,
            "sampler_name": "euler",
            "scheduler": "normal",
            "denoise": 1.0,
            "model": ["4", 0],
            "positive": ["6", 0],
            "negative": ["7", 0],
            "latent_image": ["5", 0],
        },
    },
    "4": {
        "class_type": "CheckpointLoaderSimple",
        "inputs": {
            "ckpt_name": "auto",
        },
    },
    "5": {
        "class_type": "EmptyLatentImage",
        "inputs": {
            "width": 1024,
            "height": 1024,
            "batch_size": 1,
        },
    },
    "6": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "{{PROMPT}}",
            "clip": ["4", 1],
        },
    },
    "7": {
        "class_type": "CLIPTextEncode",
        "inputs": {
            "text": "bad quality, blurry, ugly, deformed",
            "clip": ["4", 1],
        },
    },
    "8": {
        "class_type": "VAEDecode",
        "inputs": {
            "samples": ["3", 0],
            "vae": ["4", 2],
        },
    },
    "9": {
        "class_type": "SaveImage",
        "inputs": {
            "filename_prefix": "librarian",
            "images": ["8", 0],
        },
    },
}


def _load_comfyui_workflow(prompt: str) -> dict:
    """Load workflow template and inject the prompt text."""
    if COMFYUI_WORKFLOW_PATH.exists():
        try:
            workflow = json.loads(COMFYUI_WORKFLOW_PATH.read_text(encoding="utf-8"))
        except Exception as e:
            log.warning("Failed to load ComfyUI workflow template, using default: %s", e)
            workflow = json.loads(json.dumps(_DEFAULT_COMFYUI_WORKFLOW))
    else:
        workflow = json.loads(json.dumps(_DEFAULT_COMFYUI_WORKFLOW))

    # Walk the workflow and replace {{PROMPT}} placeholder
    workflow_str = json.dumps(workflow)
    workflow_str = workflow_str.replace("{{PROMPT}}", prompt.replace('"', '\\"'))
    return json.loads(workflow_str)


def _generate_comfyui(prompt: str, provider: ImageProvider) -> ImageGenResult:
    """Generate image via ComfyUI API."""
    base = provider.base_url or "http://localhost:8188"
    base = base.rstrip("/")

    workflow = _load_comfyui_workflow(prompt)
    client_id = str(uuid.uuid4())

    try:
        # Queue the prompt
        resp = requests.post(
            f"{base}/prompt",
            json={"prompt": workflow, "client_id": client_id},
            timeout=10,
        )
        resp.raise_for_status()
        prompt_id = resp.json()["prompt_id"]
        log.info("ComfyUI prompt queued: %s", prompt_id)

        # Poll for completion
        max_wait = 300  # 5 minutes
        poll_interval = 2
        elapsed = 0

        while elapsed < max_wait:
            time.sleep(poll_interval)
            elapsed += poll_interval

            hist_resp = requests.get(f"{base}/history/{prompt_id}", timeout=10)
            hist_resp.raise_for_status()
            history = hist_resp.json()

            if prompt_id in history:
                outputs = history[prompt_id].get("outputs", {})
                # Find the SaveImage node output
                for node_id, node_output in outputs.items():
                    images = node_output.get("images", [])
                    if images:
                        img_info = images[0]
                        filename = img_info["filename"]
                        subfolder = img_info.get("subfolder", "")

                        # Download the image
                        params = {"filename": filename}
                        if subfolder:
                            params["subfolder"] = subfolder
                        img_resp = requests.get(f"{base}/view", params=params, timeout=30)
                        img_resp.raise_for_status()

                        # Save locally
                        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
                        ext = Path(filename).suffix or ".png"
                        local_name = f"{uuid.uuid4().hex[:12]}{ext}"
                        local_path = OUTPUT_DIR / local_name
                        local_path.write_bytes(img_resp.content)

                        return ImageGenResult(
                            success=True,
                            image_path=str(local_path),
                            image_url=f"/generated-images/{local_name}",
                            prompt=prompt,
                            provider="comfyui",
                        )

        return ImageGenResult(
            success=False, error="ComfyUI generation timed out", prompt=prompt, provider="comfyui",
        )

    except requests.ConnectionError:
        return ImageGenResult(
            success=False, error=f"Cannot connect to ComfyUI at {base}", prompt=prompt, provider="comfyui",
        )
    except Exception as e:
        return ImageGenResult(
            success=False, error=f"ComfyUI error: {e}", prompt=prompt, provider="comfyui",
        )


# ── OpenAI-compatible provider ───────────────────────────────────────

def _generate_openai(prompt: str, provider: ImageProvider) -> ImageGenResult:
    """Generate image via OpenAI-compatible images API."""
    base = (provider.base_url or "https://api.openai.com/v1").rstrip("/")
    api_key = provider.api_key or os.environ.get("OPENAI_API_KEY", "")

    if not api_key:
        return ImageGenResult(
            success=False, error="No API key for OpenAI image generation", prompt=prompt, provider="openai",
        )

    try:
        resp = requests.post(
            f"{base}/images/generations",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json={
                "prompt": prompt,
                "n": 1,
                "size": "1024x1024",
            },
            timeout=120,
        )
        resp.raise_for_status()
        data = resp.json()

        # OpenAI returns either url or b64_json
        image_data = data["data"][0]
        image_url = image_data.get("url")
        b64 = image_data.get("b64_json")

        if b64:
            import base64
            OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
            local_name = f"{uuid.uuid4().hex[:12]}.png"
            local_path = OUTPUT_DIR / local_name
            local_path.write_bytes(base64.b64decode(b64))
            return ImageGenResult(
                success=True,
                image_path=str(local_path),
                image_url=f"/generated-images/{local_name}",
                prompt=prompt,
                provider="openai",
            )

        if image_url:
            return ImageGenResult(
                success=True,
                image_url=image_url,
                prompt=prompt,
                provider="openai",
            )

        return ImageGenResult(
            success=False, error="No image in response", prompt=prompt, provider="openai",
        )

    except requests.ConnectionError:
        return ImageGenResult(
            success=False, error=f"Cannot connect to image API at {base}", prompt=prompt, provider="openai",
        )
    except Exception as e:
        return ImageGenResult(
            success=False, error=f"OpenAI image error: {e}", prompt=prompt, provider="openai",
        )


# ── Provider registry ────────────────────────────────────────────────

_GENERATORS = {
    "comfyui": _generate_comfyui,
    "openai": _generate_openai,
}


# ── Public API ────────────────────────────────────────────────────────

def generate_image(prompt: str, **kwargs) -> ImageGenResult:
    """Generate an image, trying each configured provider in order.

    Falls through the provider chain until one succeeds or all fail.
    """
    providers = _parse_providers()

    if not providers:
        return ImageGenResult(
            success=False,
            error="No image providers configured. Set IMAGE_PROVIDERS in .env (e.g. comfyui|http://localhost:8188 or openai||sk-xxx)",
            prompt=prompt,
        )

    errors = []
    for provider in providers:
        gen_fn = _GENERATORS.get(provider.type)
        if not gen_fn:
            errors.append(f"Unknown provider type: {provider.type}")
            continue

        log.info("Trying image provider: %s (%s)", provider.type, provider.base_url or "default")
        result = gen_fn(prompt, provider)

        if result.success:
            return result

        log.warning("Provider %s failed: %s", provider.type, result.error)
        errors.append(f"{provider.type}: {result.error}")

    return ImageGenResult(
        success=False,
        error="All providers failed:\n" + "\n".join(f"  - {e}" for e in errors),
        prompt=prompt,
    )
