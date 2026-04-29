"""
model_factory.py

Model factory for building OpenRouter models with prompt caching support.
Supports both MiniMax (auto-cached) and Anthropic (explicit cache_control) models.

FIXES applied vs colleague's PR:
  1. agno.models.openrouter.OpenRouter does not exist — replaced with OpenAIChat
  2. CachingOpenRouter._format_message used a non-existent Agno method — replaced
     with the correct request_kwargs hook that OpenAIChat actually exposes
  3. extract_json min() scan picks up mid-sentence braces — replaced with
     brace-counting approach merged into utils.parse_json
  4. build_model return type annotation fixed to OpenAIChat
"""

import json
import logging
import os
import re
from typing import Any

from dotenv import load_dotenv

# ✅ FIX 1 — agno.models.openrouter does NOT exist.
# OpenAIChat is the correct Agno wrapper for any OpenAI-compatible endpoint.
from agno.models.openai import OpenAIChat

load_dotenv()

logger = logging.getLogger(__name__)

OPENROUTER_API_KEY = os.getenv("OPENROUTER_API_KEY")


# ── JSON Parsing ──────────────────────────────────────────────────────────────

def extract_json(raw: Any) -> dict | list:
    """
    Robustly extract the first valid JSON object or array from model output.

    Handles:
    - Clean JSON strings
    - Markdown fences  ```json ... ```
    - Extra text before/after JSON  (fixes colleague's min() scan issue)
    - Agno response objects (unwraps .content automatically)
    - List of content blocks

    Replaces both the old utils.parse_json AND the PR's extract_json —
    import this from model_factory everywhere.
    """
    # Unwrap Agno response object
    if hasattr(raw, "content"):
        raw = raw.content

    # Flatten list of content blocks (some models return this)
    if isinstance(raw, list):
        raw = " ".join(
            b.get("text", "") if isinstance(b, dict) else str(b)
            for b in raw
        )

    if not isinstance(raw, str):
        raw = str(raw)

    # Strip markdown fences
    fenced = re.search(r"```(?:json|JSON)?\s*([\s\S]*?)```", raw)
    if fenced:
        raw = fenced.group(1).strip()

    # Fast path — clean JSON
    try:
        return json.loads(raw.strip())
    except json.JSONDecodeError:
        pass

    # ✅ FIX 3 — brace-counting instead of min() scan.
    # min() picks up the first { or [ character anywhere, including inside
    # sentences like "Here is your result {". Brace-counting finds the
    # first *complete* balanced JSON block.
    for opener, closer in [("{", "}"), ("[", "]")]:
        count, start = 0, None
        for i, ch in enumerate(raw):
            if ch == opener:
                if start is None:
                    start = i
                count += 1
            elif ch == closer:
                count -= 1
                if count == 0 and start is not None:
                    try:
                        return json.loads(raw[start:i + 1])
                    except json.JSONDecodeError:
                        start, count = None, 0  # keep scanning

    logger.error(f"extract_json: no valid JSON found in:\n{raw[:400]}")
    return {}


def validate_bare_list(content: dict | list, response_model: type) -> Any:
    """
    Auto-wrap bare list responses if the response model has a single list field.
    MiniMax often returns [...] instead of {"field": [...]}.
    """
    if not isinstance(content, list):
        return content

    fields = getattr(response_model, "model_fields", {})
    if len(fields) != 1:
        return content

    (name, info), = fields.items()
    if hasattr(info.annotation, "__origin__") and info.annotation.__origin__ is list:
        return {name: content}

    return content


# ── CachingOpenRouter (Anthropic explicit cache_control) ──────────────────────

class CachingOpenRouter(OpenAIChat):
    """
    Subclass of OpenAIChat that injects cache_control: ephemeral markers
    on system message content blocks.

    ONLY use this when enable_caching=True (i.e. primary model is Anthropic).
    MiniMax auto-caches at the provider level — cache_control markers are
    silently ignored by MiniMax and add unnecessary payload.

    ✅ FIX 2 — _format_message does not exist on OpenAIChat.
    The correct extension point is to override get_request_kwargs() and
    patch the messages list there, which is what Agno actually calls before
    sending the HTTP request.
    """

    def get_request_kwargs(self, *args, **kwargs) -> dict:
        request_kwargs = super().get_request_kwargs(*args, **kwargs)

        messages = request_kwargs.get("messages", [])
        patched = []
        for msg in messages:
            if msg.get("role") == "system" and isinstance(msg.get("content"), str):
                # Convert string system content to block list with cache_control
                patched.append({
                    **msg,
                    "content": [
                        {
                            "type": "text",
                            "text": msg["content"],
                            "cache_control": {"type": "ephemeral"},
                        }
                    ],
                })
            else:
                patched.append(msg)

        request_kwargs["messages"] = patched
        return request_kwargs


# ── Model Factory ─────────────────────────────────────────────────────────────

def _build_extra_body(
    primary_model: str,
    fallback_models: list[str],
    pin_anthropic: bool,
) -> dict:
    """
    Build the extra_body dict for OpenRouter API.
    Handles provider pinning and fallback model chain.
    """
    body: dict = {}

    if pin_anthropic:
        body["provider"] = {
            "order": ["Anthropic"],
            "allow_fallbacks": False,
        }

    chain = [primary_model]
    seen = {primary_model}
    for m in fallback_models:
        if m and m not in seen:
            chain.append(m)
            seen.add(m)
        if len(chain) >= 3:
            break

    if len(chain) > 1:
        body["models"] = chain

    return body


def build_model(
    *,
    model_id: str,
    enable_caching: bool = False,
    fallback_models: list[str] | None = None,
    temperature: float = 0.3,
    max_tokens: int = 4096,
) -> OpenAIChat:                          # ✅ FIX 4 — return type is OpenAIChat
    """
    Build an OpenAIChat-compatible model pointed at OpenRouter.

    Args:
        model_id:        Primary model  e.g. "minimax/minimax-m2.5"
                         or "anthropic/claude-haiku-4-5-20251001"
        enable_caching:  True  → CachingOpenRouter (Anthropic cache_control blocks)
                         False → plain OpenAIChat  (MiniMax auto-caches at provider)
        fallback_models: Up to 2 fallback model IDs (3 total including primary)
        temperature:     Sampling temperature
        max_tokens:      Max response tokens

    Returns:
        Configured OpenAIChat (or CachingOpenRouter) instance
    """
    if fallback_models is None:
        fallback_models = []

    pin_anthropic = model_id.startswith("anthropic/")
    model_cls = CachingOpenRouter if enable_caching else OpenAIChat
    extra_body = _build_extra_body(model_id, fallback_models, pin_anthropic)

    return model_cls(
        id=model_id,
        api_key=OPENROUTER_API_KEY,
        base_url="https://openrouter.ai/api/v1",
        temperature=temperature,
        max_tokens=max_tokens,
        **({"extra_body": extra_body} if extra_body else {}),
    )


# ── Config Helpers ─────────────────────────────────────────────────────────────

def _parse_fallback_models(env_var: str) -> list[str]:
    value = os.getenv(env_var, "").strip()
    if not value:
        return []
    return [m.strip() for m in value.split(",") if m.strip()]


def _parse_bool(env_var: str, default: bool = False) -> bool:
    return os.getenv(env_var, "").strip().lower() in ("true", "1", "yes", "on") \
        if os.getenv(env_var) else default


def get_model_config(agent_type: str) -> dict:
    """
    Get model configuration for a specific agent type from environment.

    Args:
        agent_type: One of "parser", "triage", "reply"

    Returns:
        Dict with keys: model_id, enable_caching, fallback_models
    """
    prefix = agent_type.upper()
    return {
        "model_id":        os.getenv(f"{prefix}_MODEL_ID", "minimax/minimax-m2.5"),
        "enable_caching":  _parse_bool(f"{prefix}_ENABLE_CACHING", default=False),
        "fallback_models": _parse_fallback_models(f"{prefix}_FALLBACK_MODELS"),
    }