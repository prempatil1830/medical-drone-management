"""
app/services/explain.py — Provider-agnostic Explanation Service with Grounding Guard.

Responsibilities:
1. Extract sanitized dispatch facts (decisions, weather, candidates, route, safety).
2. Deterministic template summary: build_template_summary(facts).
3. Provider-agnostic LLM client (Groq, OpenAI, etc.) that times out after LLM_TIMEOUT_SECONDS (default 5).
4. Grounding Guard: extracts tokens/numbers from LLM text and ensures they are grounded in facts.
   If ungrounded, discards LLM text and retains template summary.
5. Weather note generator: builds a plain-English note from weather observation (safe for hospital users).
"""

from __future__ import annotations

import re
import math
import httpx
from typing import Any, Optional
from datetime import datetime, timezone

UTC = timezone.utc

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)


def extract_dispatch_facts(
    request: dict,
    decisions: list[dict],
    weather_obs: Optional[dict] = None,
    candidate_count: Optional[int] = None,
    route_result: Optional[Any] = None,
    safety_result: Optional[Any] = None,
    mission: Optional[dict] = None,
) -> dict[str, Any]:
    """
    Extract factual numbers, IDs, and states strictly without user names or emails.
    """
    req_id = str(request.get("request_id") or request.get("id") or "")
    med_type = request.get("medical_type", "")
    med_type_str = med_type.value if hasattr(med_type, "value") else str(med_type)
    urgency = request.get("urgency", "")
    urgency_str = urgency.value if hasattr(urgency, "value") else str(urgency)

    # Decisions trail
    decision_items = []
    for d in decisions:
        decision_items.append({
            "agent_name": d.get("agent_name"),
            "decision": d.get("decision"),
            "score": d.get("score"),
            "reason": d.get("reason"),
        })

    # Weather observation
    weather_info = None
    if weather_obs:
        cond = weather_obs.get("flight_condition") or weather_obs.get("condition") or "UNKNOWN"
        prob = weather_obs.get("probability")
        if prob is not None:
            prob = min(0.999, round(float(prob), 4))
        raw = weather_obs.get("raw_weather_snapshot") or {}
        current = raw.get("current") or {}
        weather_info = {
            "condition": cond,
            "probability": prob,
            "temperature_c": current.get("temp_c"),
            "wind_kph": current.get("wind_kph"),
            "humidity": current.get("humidity"),
            "precipitation_mm": current.get("precip_mm"),
            "vis_km": current.get("vis_km"),
            "reason": weather_obs.get("reason"),
        }

    # Route info
    route_info = None
    if route_result:
        dist = getattr(route_result, "distance_km", None)
        eta = getattr(route_result, "eta_minutes", None)
        batt = getattr(route_result, "battery_required_pct", None)
        route_info = {
            "distance_km": round(float(dist), 2) if dist is not None else None,
            "eta_minutes": round(float(eta), 1) if eta is not None else None,
            "battery_required_pct": round(float(batt), 1) if batt is not None else None,
        }
    elif mission:
        dist = mission.get("distance_km")
        eta = mission.get("eta_minutes")
        batt = mission.get("battery_required_pct")
        route_info = {
            "distance_km": round(float(dist), 2) if dist is not None else None,
            "eta_minutes": round(float(eta), 1) if eta is not None else None,
            "battery_required_pct": round(float(batt), 1) if batt is not None else None,
        }

    # Safety info
    safety_info = None
    if safety_result:
        safety_info = {
            "decision": getattr(safety_result, "decision", None),
            "reason": getattr(safety_result, "reason", None),
        }

    # Drone ID
    allocated_drone_id = None
    if mission:
        allocated_drone_id = mission.get("drone_id")
    elif request.get("assigned_drone_id"):
        allocated_drone_id = request.get("assigned_drone_id")

    return {
        "request_id": req_id,
        "medical_type": med_type_str,
        "urgency": urgency_str,
        "quantity": request.get("quantity"),
        "weight_kg": request.get("weight_kg"),
        "allocated_drone_id": allocated_drone_id,
        "candidate_count": candidate_count,
        "decisions": decision_items,
        "weather": weather_info,
        "route": route_info,
        "safety": safety_info,
    }


def build_template_summary(facts: dict[str, Any]) -> str:
    """
    Deterministic plain-English summary built exclusively from facts.
    """
    parts = []

    # 1. Request & Priority
    med_type = facts.get("medical_type", "Supplies")
    urgency = facts.get("urgency", "NORMAL")
    prio_decision = "Normal"
    for d in facts.get("decisions", []):
        if d.get("agent_name") == "PriorityAgent":
            prio_decision = d.get("decision", "Normal")
            break
    parts.append(f"Request for {med_type} (urgency {urgency}) was classified as {prio_decision} priority.")

    # 2. Weather
    weather = facts.get("weather")
    if weather:
        cond = weather.get("condition", "UNKNOWN")
        prob = weather.get("probability")
        reason = weather.get("reason") or ""
        reason_lower = reason.lower()
        is_forced_or_api_fail = (
            "forced" in reason_lower
            or "demo" in reason_lower
            or "fail" in reason_lower
            or "api" in reason_lower
            or "error" in reason_lower
        )

        if prob is None or prob == 0 or is_forced_or_api_fail:
            fall_reason = reason or "weather evaluation unavailable"
            parts.append(
                f"Weather could not be evaluated by the model ({fall_reason}), so the flight was treated as UNSAFE."
            )
            parts.append(f"Dispatch was halted due to unsafe weather ({fall_reason}).")
            return " ".join(parts)
        else:
            prob_str = f" with {prob*100:.1f}% confidence"
            parts.append(f"Weather conditions were evaluated as {cond}{prob_str}.")
            if cond == "UNSAFE":
                fail_reason = reason or "unfavorable flight parameters"
                parts.append(f"Dispatch was halted due to unsafe weather ({fail_reason}).")
                return " ".join(parts)

    # 3. Allocation & Candidates
    drone_id = facts.get("allocated_drone_id")
    cand_count = facts.get("candidate_count")
    if drone_id:
        cand_str = f" from {cand_count} candidates" if cand_count is not None else ""
        parts.append(f"Drone {drone_id} was successfully selected{cand_str}.")
    else:
        # Check if halted at allocation
        alloc_reason = None
        for d in facts.get("decisions", []):
            if d.get("agent_name") == "AllocationAgent":
                alloc_reason = d.get("reason")
        parts.append(f"No drone was allocated ({alloc_reason or 'no feasible drone available'}).")
        return " ".join(parts)

    # 4. Route
    route = facts.get("route")
    if route and route.get("distance_km") is not None:
        dist = route.get("distance_km")
        eta = route.get("eta_minutes")
        batt = route.get("battery_required_pct")
        parts.append(f"The mission covers {dist} km with an estimated flight time of {eta} minutes requiring {batt}% battery.")

    # 5. Safety
    safety = facts.get("safety")
    if safety:
        s_dec = safety.get("decision", "PASS")
        if s_dec == "PASS":
            parts.append("All safety constraints passed verification.")
        else:
            s_reas = safety.get("reason") or "safety constraints check failed"
            parts.append(f"Safety gate resulted in {s_dec} ({s_reas}).")

    return " ".join(parts)


def build_weather_note(weather_obs: Optional[dict[str, Any]]) -> str:
    """
    Build one plain-English sentence summarizing weather without leaking ML internals.
    """
    if not weather_obs:
        return "Weather conditions confirmed within normal limits."
    cond = weather_obs.get("flight_condition") or weather_obs.get("condition") or "SAFE"
    raw = weather_obs.get("raw_weather_snapshot") or {}
    curr = raw.get("current") or {}
    wind = curr.get("wind_kph")
    vis = curr.get("vis_km")

    details = []
    if wind is not None:
        details.append(f"wind at {wind} km/h")
    if vis is not None:
        details.append(f"visibility {vis} km")

    detail_str = f" ({', '.join(details)})" if details else ""
    if cond == "SAFE":
        return f"Flight conditions are clear and safe for drone operations{detail_str}."
    elif cond == "CAUTION":
        return f"Flight conditions require caution due to moderate atmospheric factors{detail_str}."
    else:
        return f"Flight conditions are currently unsafe for drone transit{detail_str}."


async def refine_weather_note(weather_obs: Optional[dict[str, Any]]) -> str:
    """
    Refine weather note using LLM if enabled, falling back to deterministic template note under grounding guard.
    """
    template_note = build_weather_note(weather_obs)
    if not settings.LLM_API_KEY or not weather_obs:
        return template_note
    try:
        facts = {"weather": weather_obs}
        llm_text = await call_llm(facts, template_note)
        if llm_text and verify_grounding(llm_text, facts):
            return llm_text
    except Exception as exc:
        log.warning("refine_weather_note_failed", error=str(exc))
    return template_note


# ── Grounding Guard ───────────────────────────────────────────────────────────

def _extract_tokens_to_verify(text: str) -> list[str]:
    """
    Extract numbers, IDs, and code-like tokens that must be verified against facts.
    Examples: '42', '12.5', 'DRN-001', 'REQ-12345678', '99.9%'
    """
    # Normalize unicode spaces (e.g. narrow no-break space \u202f, non-breaking space \xa0)
    normalized = re.sub(r'[\s\u2000-\u200b\u202f\u00a0]+', ' ', text)
    # Find numbers (integers, floats, percentages) and hyphenated alphanumeric IDs
    pattern = r'\b[A-Za-z]+-[A-Za-z0-9_-]+\b|\b\d+(?:\.\d+)?%?\b'
    matches = re.findall(pattern, normalized)
    cleaned = []
    for m in matches:
        token = m.strip()
        if token:
            cleaned.append(token)
    return cleaned


def _collect_fact_values(obj: Any) -> list[str]:
    """Recursively collect string representations and numbers from facts."""
    values = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            if k in ("agent_name", "decision", "status"):
                continue  # Standard enum words
            values.extend(_collect_fact_values(v))
    elif isinstance(obj, list):
        for item in obj:
            values.extend(_collect_fact_values(item))
    elif obj is not None:
        values.append(str(obj))
    return values


NUMBER_WORDS: dict[str, str] = {
    "zero": "0", "one": "1", "two": "2", "three": "3", "four": "4",
    "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",
    "ten": "10", "eleven": "11", "twelve": "12", "thirteen": "13",
    "fourteen": "14", "fifteen": "15", "sixteen": "16", "seventeen": "17",
    "eighteen": "18", "nineteen": "19", "twenty": "20", "thirty": "30",
    "forty": "40", "fifty": "50", "sixty": "60", "seventy": "70",
    "eighty": "80", "ninety": "90", "hundred": "100", "thousand": "1000",
}

WEATHER_CONDITION_TERMS: list[str] = [
    "wind", "winds", "gust", "gusts", "rain", "raining", "rainy",
    "storm", "storms", "stormy", "fog", "foggy", "haze", "hazy",
    "visibility", "humidity", "temperature", "thunder", "thunders", "snow", "snowing",
]


def _normalize_number_words(text: str) -> str:
    """Replace English number words with digits (e.g. 'three' -> '3')."""
    def _repl(match: re.Match) -> str:
        w = match.group(0).lower()
        return NUMBER_WORDS.get(w, match.group(0))

    pattern = r'\b(' + '|'.join(NUMBER_WORDS.keys()) + r')\b'
    return re.sub(pattern, _repl, text, flags=re.IGNORECASE)


def _check_qualitative_weather_terms(llm_text: str, facts: dict[str, Any], template_text: str = "") -> bool:
    """
    Any qualitative weather or condition term in the LLM text (wind, gust, rain,
    storm, fog, haze, visibility, humidity, temperature, thunder, snow) must also
    appear in the facts or the template text.
    """
    llm_lower = llm_text.lower()
    allowed_corpus = (str(facts) + " " + template_text).lower()

    for term in WEATHER_CONDITION_TERMS:
        # Check if term appears as word or prefix
        pattern = r'\b' + re.escape(term)
        if re.search(pattern, llm_lower):
            # Must appear in facts or template text
            if not re.search(pattern, allowed_corpus):
                log.warning("grounding_guard_rejected_weather_term", term=term)
                return False
    return True


def verify_grounding(
    llm_text: str,
    facts: dict[str, Any],
    tolerance: float = 0.5,
    template_text: str = "",
) -> bool:
    """
    Hardened Grounding guard:
    1. Check qualitative weather/condition terms (wind, gust, rain, storm, etc.)
       must appear in facts or template text.
    2. Normalize number words ('three' -> '3', 'seven' -> '7') to digits.
    3. Extract numbers and IDs, verify each against facts.
    """
    if not llm_text or not llm_text.strip():
        return False

    # 1. Qualitative weather terms check
    if not _check_qualitative_weather_terms(llm_text, facts, template_text):
        return False

    # 2. Number words normalized to digits
    normalized_text = _normalize_number_words(llm_text)

    tokens = _extract_tokens_to_verify(normalized_text)
    raw_fact_values = _collect_fact_values(facts)

    # Flatten fact numbers and fact strings
    fact_numbers: list[float] = []
    fact_strings: set[str] = set()

    for f in raw_fact_values:
        fact_strings.add(f.lower().strip())
        # Try extracting numbers from fact strings
        for num_match in re.findall(r'\b\d+(?:\.\d+)?\b', f):
            try:
                fact_numbers.append(float(num_match))
            except ValueError:
                pass

    for token in tokens:
        clean_token = token.rstrip("%").strip()
        # Is it a number?
        try:
            val = float(clean_token)
            # Check if within tolerance or percentage (e.g. 0.99 -> 99) of any fact number
            matched = False
            for f_val in fact_numbers:
                if math.isclose(val, f_val, abs_tol=tolerance):
                    matched = True
                    break
                # Percentage representation check (0.85 -> 85)
                if math.isclose(val, f_val * 100.0, abs_tol=tolerance):
                    matched = True
                    break
                if math.isclose(val * 100.0, f_val, abs_tol=tolerance):
                    matched = True
                    break
            if not matched:
                log.warning("grounding_guard_rejected_number", token=token, value=val)
                return False
            continue
        except ValueError:
            pass

        # It's an ID or text token (e.g., 'DRN-001')
        token_lower = token.lower()
        if not any(token_lower in f or f in token_lower for f in fact_strings):
            log.warning("grounding_guard_rejected_id", token=token)
            return False

    return True


# ── LLM Client ────────────────────────────────────────────────────────────────

def get_system_prompt() -> str:
    return (
        "You are an AI assistant in a medical drone management system. "
        "Your task is to reword the provided factual dispatch summary into clear, concise, "
        "professional English for operators. "
        "CRITICAL INSTRUCTION: Use ONLY the facts provided. Do NOT invent new numbers, percentages, "
        "or identifiers. Do NOT guess weather metrics (e.g. wind speed) or drone IDs."
    )


async def call_llm(facts: dict[str, Any], template_text: str) -> Optional[str]:
    """
    Call the configured LLM provider to reword the template summary.
    Never logs the API key or raw prompt at INFO.
    Returns the generated string, or None if disabled/failed.
    """
    api_key = settings.LLM_API_KEY
    if not api_key:
        return None

    provider = (settings.LLM_PROVIDER or "groq").lower().strip()
    model = settings.LLM_MODEL or "llama-3.3-70b-versatile"
    timeout = float(settings.LLM_TIMEOUT_SECONDS or 5.0)

    # Build prompt
    prompt = (
        f"Factual dispatch data:\n{facts}\n\n"
        f"Baseline deterministic summary:\n{template_text}\n\n"
        f"Please reword the baseline summary cleanly while keeping all numbers, states, and IDs strictly accurate:"
    )

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

    # Endpoint selection (OpenAI-compatible for Groq and OpenAI)
    if provider in ("groq", "openai"):
        url = "https://api.groq.com/openai/v1/chat/completions" if provider == "groq" else "https://api.openai.com/v1/chat/completions"
        payload = {
            "model": model,
            "messages": [
                {"role": "system", "content": get_system_prompt()},
                {"role": "user", "content": prompt},
            ],
            "temperature": 0.2,
            "max_tokens": 600,
        }
    else:
        # Fallback or generic provider
        return None

    try:
        async with httpx.AsyncClient(timeout=timeout) as client:
            resp = await client.post(url, headers=headers, json=payload)
            if resp.status_code == 200:
                data = resp.json()
                text = data["choices"][0]["message"]["content"].strip()
                return text
            else:
                log.warning("llm_api_error_response", status_code=resp.status_code)
                return None
    except Exception as exc:
        log.warning("llm_call_exception", error=str(exc))
        return None


def strip_markdown(text: str) -> str:
    """
    Remove common markdown artifacts (bold, italics, code formatting, bullet points)
    leaving clean plain English text.
    """
    if not text:
        return ""
    # Strip bold/italic asterisks and underscores: **bold** -> bold, *italic* -> italic
    cleaned = re.sub(r'[*_]{1,3}([^*_]+)[*_]{1,3}', r'\1', text)
    # Strip inline code backticks: `code` -> code
    cleaned = re.sub(r'`([^`]+)`', r'\1', cleaned)
    # Strip leading markdown list markers: "- ", "* ", "1. "
    cleaned = re.sub(r'^\s*[-*•]\s+', '', cleaned, flags=re.MULTILINE)
    cleaned = re.sub(r'^\s*\d+\.\s+', '', cleaned, flags=re.MULTILINE)
    # Collapse multiple whitespaces/newlines to clean single spacing
    cleaned = re.sub(r'[ \t]+', ' ', cleaned)
    cleaned = re.sub(r'\n+', ' ', cleaned)
    return cleaned.strip()


async def generate_explanation(facts: dict[str, Any]) -> dict[str, Any]:
    """
    Generate explanation for dispatch:
    1. Build deterministic template summary.
    2. Attempt LLM enhancement if configured.
    3. Run grounding guard.
    Returns: {"text": str, "source": "template" | "llm", "generated_at": datetime, "attempt": int}
    """
    template_text = build_template_summary(facts)
    now = datetime.now(UTC)

    # Attempt LLM
    llm_text = await call_llm(facts, template_text)
    if llm_text:
        is_grounded = verify_grounding(llm_text, facts, template_text=template_text)
        if is_grounded:
            cleaned_text = strip_markdown(llm_text)
            return {
                "text": cleaned_text,
                "source": "llm",
                "generated_at": now,
                "attempt": 1,
            }
        else:
            log.info("grounding_guard_discarded_llm_text", reason="ungrounded_facts_detected")

    return {
        "text": template_text,
        "source": "template",
        "generated_at": now,
        "attempt": 1,
    }
