"""AI Threat Analyst - sends honeypot session data to a chat model for analysis.

Supports OpenAI, Google Gemini and Anthropic Claude. Uses only the standard
library (urllib) so no extra dependency is required and it works in the frozen
PyInstaller build.
"""
from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

PROVIDERS = ("openai", "gemini", "claude")

DEFAULT_MODELS = {
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.0-flash",
    "claude": "claude-haiku-4-5-20251001",
}

PROVIDER_LABELS = {
    "openai": "OpenAI",
    "gemini": "Google Gemini",
    "claude": "Anthropic Claude",
}

_SYSTEM_PROMPT = (
    "You are a cybersecurity threat analyst reviewing honeypot capture data. "
    "A honeypot is a decoy system intentionally exposed to the internet to attract and log intrusion attempts — "
    "every connection is unsolicited. You will be given session data including source IP, geolocation, "
    "login attempts, and HTTP requests. Produce a concise analysis in this format:\n\n"
    "ACTOR: What kind of attacker or automated tool this most likely is "
    "(e.g. Mirai botnet, credential stuffing tool, Shodan scanner, vulnerability scanner, manual attacker).\n\n"
    "INTENT: What the attacker was trying to accomplish.\n\n"
    "SEVERITY: low / medium / high — base this on: number of attempts, credential sophistication, "
    "targeted paths, whether the source IP is private/loopback (private = likely a local test, low severity), "
    "and known attack patterns.\n\n"
    "RECOMMENDATION: One or two concrete actions the honeypot operator can take "
    "(e.g. block the IP range, report to AbuseIPDB, check if the targeted service is exposed elsewhere).\n\n"
    "Be direct and factual. If the source IP is a private/loopback address (127.x, 10.x, 192.168.x, 172.16-31.x) "
    "note that it is likely a local test and rate severity as low. "
    "Do not invent data not present in the session. Keep the whole response under 220 words."
)

_TIMEOUT_SECONDS = 45


class AIError(Exception):
    """Raised when an AI request cannot be completed."""


def is_configured(ai_config: dict[str, Any] | None) -> bool:
    if not ai_config:
        return False
    return bool(ai_config.get("enabled")) and bool(str(ai_config.get("api_key", "")).strip())


def resolve_model(provider: str, model: str | None) -> str:
    model = (model or "").strip()
    if model:
        return model
    return DEFAULT_MODELS.get(provider, "")


def build_session_prompt(session: dict[str, Any], events: list[dict[str, Any]]) -> str:
    lines = [
        "HONEYPOT SESSION DATA",
        f"Service: {session.get('service', 'unknown')}",
        f"Source IP: {session.get('source_ip', 'unknown')}",
        f"Source port: {session.get('source_port', 'unknown')}",
        f"Country: {session.get('country') or 'unknown'} "
        f"({session.get('country_code') or '--'})",
        f"City: {session.get('city') or 'unknown'}",
        f"Started: {session.get('started_at', 'unknown')}",
        f"Ended: {session.get('ended_at') or 'still active'}",
        f"Duration (s): {session.get('duration_sec') if session.get('duration_sec') is not None else 'n/a'}",
        f"Total events: {len(events)}",
        "",
        "EVENTS:",
    ]
    if not events:
        lines.append("(no events recorded)")
    for index, event in enumerate(events[:60], start=1):
        data = event.get("data") or {}
        event_type = event.get("event_type", "event")
        if event_type == "auth_attempt":
            method = data.get("method", "password")
            detail = f"user={data.get('username', '')!r} pass={data.get('password', '')!r} method={method}"
        elif event_type == "http_request":
            detail = (
                f"{data.get('method', 'GET')} {data.get('path', '/')} "
                f"ua={data.get('user_agent') or '-'!r}"
            )
        else:
            detail = json.dumps(data, ensure_ascii=False)[:300]
        lines.append(f"{index}. [{event.get('timestamp', '')}] {event_type}: {detail}")
    if len(events) > 60:
        lines.append(f"... ({len(events) - 60} more events omitted)")
    return "\n".join(lines)


def analyze(provider: str, api_key: str, model: str, prompt: str) -> str:
    """Send a prompt to the selected provider and return the text response.

    Raises AIError on any failure (network, auth, malformed response).
    """
    provider = (provider or "").strip().lower()
    api_key = (api_key or "").strip()
    if provider not in PROVIDERS:
        raise AIError(f"Unknown AI provider: {provider!r}")
    if not api_key:
        raise AIError("No API key configured.")

    model = resolve_model(provider, model)
    if provider == "openai":
        return _call_openai(api_key, model, prompt)
    if provider == "gemini":
        return _call_gemini(api_key, model, prompt)
    return _call_claude(api_key, model, prompt)


def _post_json(url: str, headers: dict[str, str], payload: dict[str, Any]) -> dict[str, Any]:
    body = json.dumps(payload).encode("utf-8")
    request = urllib.request.Request(url, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(request, timeout=_TIMEOUT_SECONDS) as response:
            raw = response.read().decode("utf-8", errors="replace")
    except urllib.error.HTTPError as exc:
        detail = ""
        try:
            detail = exc.read().decode("utf-8", errors="replace")[:400]
        except Exception:
            pass
        raise AIError(f"HTTP {exc.code} from API. {detail}".strip()) from exc
    except urllib.error.URLError as exc:
        raise AIError(f"Network error: {exc.reason}") from exc
    except Exception as exc:  # noqa: BLE001 - surface any transport failure
        raise AIError(f"Request failed: {exc}") from exc

    try:
        return json.loads(raw)
    except ValueError as exc:
        raise AIError("API returned a malformed response.") from exc


def _call_openai(api_key: str, model: str, prompt: str) -> str:
    data = _post_json(
        "https://api.openai.com/v1/chat/completions",
        {
            "Authorization": f"Bearer {api_key}",
            "Content-Type": "application/json",
        },
        {
            "model": model,
            "messages": [
                {"role": "system", "content": _SYSTEM_PROMPT},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
        },
    )
    try:
        return data["choices"][0]["message"]["content"].strip()
    except (KeyError, IndexError, AttributeError) as exc:
        raise AIError("OpenAI response missing expected content.") from exc


def _call_gemini(api_key: str, model: str, prompt: str) -> str:
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{urllib.parse.quote(model)}:generateContent?key={urllib.parse.quote(api_key)}"
    )
    data = _post_json(
        url,
        {"Content-Type": "application/json"},
        {
            "system_instruction": {"parts": [{"text": _SYSTEM_PROMPT}]},
            "contents": [{"role": "user", "parts": [{"text": prompt}]}],
            "generationConfig": {"temperature": 0.2},
        },
    )
    try:
        parts = data["candidates"][0]["content"]["parts"]
        return "".join(part.get("text", "") for part in parts).strip()
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise AIError("Gemini response missing expected content.") from exc


def _call_claude(api_key: str, model: str, prompt: str) -> str:
    data = _post_json(
        "https://api.anthropic.com/v1/messages",
        {
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "Content-Type": "application/json",
        },
        {
            "model": model,
            "max_tokens": 1024,
            "system": _SYSTEM_PROMPT,
            "messages": [{"role": "user", "content": prompt}],
        },
    )
    try:
        blocks = data["content"]
        return "".join(
            block.get("text", "") for block in blocks if block.get("type") == "text"
        ).strip()
    except (KeyError, IndexError, AttributeError, TypeError) as exc:
        raise AIError("Claude response missing expected content.") from exc
