"""Provider-agnostic LLM calls for the Creative Boardroom agents.

Default provider is local Ollama, so the demo can run without paid API calls.
Anthropic and OpenAI-compatible endpoints remain available as drop-in fallbacks.
"""
from __future__ import annotations

import os
from typing import Any

import httpx

try:
    from dotenv import load_dotenv

    load_dotenv()
    load_dotenv(".emv", override=False)
except Exception:
    pass


JSON_SYSTEM_PROMPT = (
    "You are a JSON-only assistant. Return exactly one valid JSON object. "
    "Do not include markdown, commentary, or code fences."
)


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except ValueError:
        return default


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _raise_for_status(response: httpx.Response) -> None:
    try:
        response.raise_for_status()
    except httpx.HTTPStatusError as exc:
        body = response.text[:1000]
        raise httpx.HTTPStatusError(
            f"{exc}. Response body: {body}",
            request=exc.request,
            response=exc.response,
        ) from exc


def _provider() -> str:
    return os.getenv("LLM_PROVIDER", "ollama").strip().lower()


def _ollama_model(image_b64: str | None, model: str | None) -> str:
    if model:
        return model
    if image_b64:
        return os.getenv("OLLAMA_MODEL_VISION", os.getenv("OLLAMA_MODEL", "gemma4:e2b"))
    return os.getenv("OLLAMA_MODEL_TEXT", os.getenv("OLLAMA_MODEL", "gemma4:e2b"))


def _ollama_chat(prompt: str, *, image_b64: str | None, max_tokens: int, model: str | None) -> str:
    base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434").rstrip("/")
    message: dict[str, Any] = {"role": "user", "content": prompt}
    if image_b64:
        message["images"] = [image_b64]

    payload: dict[str, Any] = {
        "model": _ollama_model(image_b64, model),
        "messages": [
            {"role": "system", "content": JSON_SYSTEM_PROMPT},
            message,
        ],
        "stream": False,
        "options": {
            "num_predict": max_tokens,
            "temperature": _env_float("LLM_TEMPERATURE", 0.2),
            "top_p": _env_float("LLM_TOP_P", 0.95),
        },
    }
    if _env_bool("OLLAMA_JSON_MODE", True):
        payload["format"] = "json"

    with httpx.Client(timeout=_env_float("LLM_TIMEOUT_SECONDS", 90.0)) as client:
        response = client.post(f"{base_url}/api/chat", json=payload)
        _raise_for_status(response)
        data = response.json()
    return data.get("message", {}).get("content", "")


def _openai_compatible_model(image_b64: str | None, model: str | None) -> str:
    if model:
        return model
    if image_b64:
        return os.getenv("OPENAI_COMPATIBLE_MODEL_VISION", os.getenv("OPENAI_COMPATIBLE_MODEL", "gemma4:e2b"))
    return os.getenv("OPENAI_COMPATIBLE_MODEL_TEXT", os.getenv("OPENAI_COMPATIBLE_MODEL", "gemma4:e2b"))


def _openai_compatible_chat(
    prompt: str, *, image_b64: str | None, max_tokens: int, model: str | None
) -> str:
    base_url = os.getenv("OPENAI_COMPATIBLE_BASE_URL", "http://localhost:11434/v1").rstrip("/")
    api_key = os.getenv("OPENAI_COMPATIBLE_API_KEY", "ollama")

    if image_b64:
        user_content: str | list[dict[str, Any]] = [
            {"type": "text", "text": prompt},
            {"type": "image_url", "image_url": {"url": f"data:image/png;base64,{image_b64}"}},
        ]
    else:
        user_content = prompt

    payload = {
        "model": _openai_compatible_model(image_b64, model),
        "max_tokens": max_tokens,
        "temperature": _env_float("LLM_TEMPERATURE", 0.2),
        "messages": [
            {"role": "system", "content": JSON_SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
        ],
    }

    headers = {"Authorization": f"Bearer {api_key}"}
    with httpx.Client(timeout=_env_float("LLM_TIMEOUT_SECONDS", 90.0)) as client:
        response = client.post(f"{base_url}/chat/completions", json=payload, headers=headers)
        _raise_for_status(response)
        data = response.json()
    return data["choices"][0]["message"]["content"]


def _anthropic_model(image_b64: str | None, model: str | None) -> str:
    if model:
        return model
    if image_b64:
        return os.getenv("ANTHROPIC_MODEL_VISION", os.getenv("ANTHROPIC_MODEL", "claude-sonnet-4-6"))
    return os.getenv("ANTHROPIC_MODEL_TEXT", os.getenv("ANTHROPIC_MODEL", "claude-haiku-4-5-20251001"))


def _anthropic_chat(prompt: str, *, image_b64: str | None, max_tokens: int, model: str | None) -> str:
    from anthropic import Anthropic

    client = Anthropic()
    if image_b64:
        content: str | list[dict[str, Any]] = [
            {
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": "image/png",
                    "data": image_b64,
                },
            },
            {"type": "text", "text": prompt},
        ]
    else:
        content = prompt

    response = client.messages.create(
        model=_anthropic_model(image_b64, model),
        max_tokens=max_tokens,
        system=JSON_SYSTEM_PROMPT,
        messages=[{"role": "user", "content": content}],
    )
    return response.content[0].text


def generate_text(prompt: str, *, max_tokens: int = 1024, model: str | None = None) -> str:
    provider = _provider()
    if provider == "ollama":
        return _ollama_chat(prompt, image_b64=None, max_tokens=max_tokens, model=model)
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        return _openai_compatible_chat(prompt, image_b64=None, max_tokens=max_tokens, model=model)
    if provider == "anthropic":
        return _anthropic_chat(prompt, image_b64=None, max_tokens=max_tokens, model=model)
    raise ValueError(f"Unsupported LLM_PROVIDER={provider!r}")


def generate_vision(
    prompt: str, image_b64: str, *, max_tokens: int = 1024, model: str | None = None
) -> str:
    provider = _provider()
    if provider == "ollama":
        return _ollama_chat(prompt, image_b64=image_b64, max_tokens=max_tokens, model=model)
    if provider in {"openai", "openai_compatible", "openai-compatible"}:
        return _openai_compatible_chat(prompt, image_b64=image_b64, max_tokens=max_tokens, model=model)
    if provider == "anthropic":
        return _anthropic_chat(prompt, image_b64=image_b64, max_tokens=max_tokens, model=model)
    raise ValueError(f"Unsupported LLM_PROVIDER={provider!r}")
