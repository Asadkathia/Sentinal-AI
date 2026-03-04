from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.request
from typing import Any

from pydantic import ValidationError

from scr.models import Category, Finding, Location, Severity, SourceInfo

PROMPT_TEMPLATE = """You are a strict code-review engine.
Return ONLY valid JSON with top-level key `findings` as an array.
Each finding should include: title, severity, confidence, category, file, location(start_line/end_line/symbol), message, recommendation(list), suggested_tests(list), suggested_patch(optional), source(rule).
Constraints:
- Max findings: {max_findings}
- High signal only, avoid style nits.
- Focus on changed code.
- Do not invent file paths or line numbers. Omit unknown fields.

Repository conventions: {conventions}

Diff and context:
{payload}
"""


def run_llm_analyzer(changes, context_map: dict, config: dict, max_findings: int) -> list[Finding]:
    provider = str(config.get("llm_provider", "openai")).lower()

    redacted = redact_payload(
        changes.diff_text or build_payload_from_context(context_map), config
    )
    prompt = PROMPT_TEMPLATE.format(
        max_findings=max_findings,
        conventions=detect_conventions(),
        payload=redacted[:20000],
    )

    if provider == "gemini":
        api_key = os.getenv("SCR_GEMINI_API_KEY")
        if not api_key:
            return []
        model = str(config.get("llm_model", "gemini-2.0-flash"))
        response_text = call_gemini(prompt, api_key=api_key, model=model)
    elif provider == "openai":
        api_key = os.getenv("SCR_OPENAI_API_KEY")
        if not api_key:
            return []
        model = str(config.get("llm_model", "gpt-4o-mini"))
        response_text = call_openai(prompt, api_key=api_key, model=model)
    else:
        return []

    if not response_text:
        return []
    return parse_llm_findings(response_text)


def redact_payload(text: str, config: dict) -> str:
    out = text
    for pattern in config.get("redact_patterns", []):
        out = re.sub(pattern, "[REDACTED]", out)
    out = re.sub(r"(?ms)^.*\.env.*$", "[REDACTED_ENV_PATH]", out)
    return out


def detect_conventions() -> str:
    hints = []
    if os.path.exists("pyproject.toml"):
        hints.append("Python project")
    if os.path.exists("package.json"):
        hints.append("Node project")
    if os.path.exists("go.mod"):
        hints.append("Go project")
    return ", ".join(hints) or "unknown"


def build_payload_from_context(context_map: dict) -> str:
    parts: list[str] = []
    for file, data in context_map.items():
        parts.append(f"# File: {file}")
        for hunk in data.get("hunks", []):
            parts.append(hunk)
    return "\n\n".join(parts)


def call_openai(prompt: str, api_key: str, model: str) -> str:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": "Return only strict JSON."},
            {"role": "user", "content": prompt},
        ],
        "response_format": {"type": "json_object"},
        "temperature": 0,
    }

    req = urllib.request.Request(
        "https://api.openai.com/v1/chat/completions",
        data=json.dumps(body).encode("utf-8"),
        headers={
            "Content-Type": "application/json",
            "Authorization": f"Bearer {api_key}",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=45) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            return data["choices"][0]["message"]["content"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError):
        return ""


def call_gemini(prompt: str, api_key: str, model: str) -> str:
    """Call Google Gemini generateContent REST API and return JSON text."""
    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/{model}"
        f":generateContent?key={api_key}"
    )

    # Instruct Gemini to return JSON
    body = {
        "contents": [
            {
                "parts": [
                    {
                        "text": (
                            "You are a strict code-review engine. "
                            "Return ONLY valid JSON — no markdown, no code fences.\n\n"
                            + prompt
                        )
                    }
                ]
            }
        ],
        "generationConfig": {
            "temperature": 0,
            "responseMimeType": "application/json",
        },
    }

    req = urllib.request.Request(
        url,
        data=json.dumps(body).encode("utf-8"),
        headers={"Content-Type": "application/json"},
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=60) as resp:
            data = json.loads(resp.read().decode("utf-8"))
            # Gemini response: candidates[0].content.parts[0].text
            return data["candidates"][0]["content"]["parts"][0]["text"]
    except (urllib.error.URLError, KeyError, json.JSONDecodeError, IndexError):
        return ""


def parse_llm_findings(response_text: str) -> list[Finding]:
    # Strip markdown fences if present (safety measure)
    text = response_text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```[a-z]*\n?", "", text)
        text = re.sub(r"\n?```$", "", text.rstrip())

    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        return []

    raw_findings = payload.get("findings", []) if isinstance(payload, dict) else []
    out: list[Finding] = []
    for item in raw_findings:
        try:
            out.append(_coerce_finding(item))
        except (ValidationError, ValueError, TypeError):
            continue
    return out


# Map alternate severity names from different LLM providers -> canonical enum values
_SEV_MAP: dict[str, str] = {
    "CRITICAL": "HIGH",
    "BLOCKER": "BLOCKER",
    "ERROR": "HIGH",
    "WARNING": "MEDIUM",
    "INFO": "LOW",
    "NIT": "NIT",
    "NOTE": "NIT",
}

# Map alternate category names -> canonical enum values
_CAT_MAP: dict[str, str] = {
    "security": "security",
    "correctness": "correctness",
    "performance": "performance",
    "maintainability": "maintainability",
    "readability": "readability",
    "structure": "structure",
    "tests": "tests",
    "docs": "docs",
    # common Gemini aliases
    "bug": "correctness",
    "bugs": "correctness",
    "vulnerability": "security",
    "vulnerabilities": "security",
    "error handling": "correctness",
    "style": "readability",
    "design": "structure",
    "documentation": "docs",
    "testing": "tests",
}


def _normalize_severity(raw: str) -> str:
    upper = raw.upper().strip()
    if upper in {s.value for s in Severity}:
        return upper
    return _SEV_MAP.get(upper, "MEDIUM")


def _normalize_category(raw: str) -> str:
    lower = raw.lower().strip()
    if lower in {c.value for c in Category}:
        return lower
    return _CAT_MAP.get(lower, "maintainability")


_CONF_MAP: dict[str, float] = {
    "CRITICAL": 0.99,
    "HIGH": 0.85,
    "MEDIUM": 0.65,
    "LOW": 0.40,
    "NIT": 0.20,
    "NONE": 0.10,
}


def _normalize_confidence(raw: Any) -> float:
    """Accept float, int, or string like 'High' / '0.9' → float in [0,1]."""
    if isinstance(raw, (int, float)):
        val = float(raw)
        return max(0.0, min(1.0, val))
    s = str(raw).upper().strip()
    if s in _CONF_MAP:
        return _CONF_MAP[s]
    try:
        return max(0.0, min(1.0, float(s)))
    except ValueError:
        return 0.5


def _coerce_finding(item: dict[str, Any]) -> Finding:
    location = item.get("location") or {}
    raw_source = item.get("source") or {}

    # Gemini sometimes returns source as a plain string (e.g. "SQL Injection")
    if isinstance(raw_source, str):
        rule_str = raw_source or "llm_generated"
        raw_source = {}
    else:
        rule_str = str(raw_source.get("rule", "llm_generated"))

    sev = _normalize_severity(str(item.get("severity", "MEDIUM")))
    category = _normalize_category(str(item.get("category", "maintainability")))
    confidence = _normalize_confidence(item.get("confidence", 0.5))

    return Finding(
        title=str(item.get("title", "LLM finding"))[:120],
        severity=Severity(sev),
        confidence=confidence,
        category=Category(category),
        file=str(item.get("file", "(unknown)")),
        location=Location(
            start_line=location.get("start_line"),
            end_line=location.get("end_line"),
            symbol=location.get("symbol"),
        ),
        message=str(item.get("message", ""))[:500],
        recommendation=[str(x) for x in item.get("recommendation", [])][:5],
        suggested_tests=[str(x) for x in item.get("suggested_tests", [])][:5],
        suggested_patch=item.get("suggested_patch"),
        source=SourceInfo(analyzer="llm", rule=rule_str),
    )

