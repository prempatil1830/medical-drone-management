"""
app/agents/priority_agent.py — Priority Agent for Phase 7.

Responsibilities
----------------
1. Accept a medical_requests document (medical_type, urgency, created_at,
   quantity, weight_kg).
2. Classify it as Critical / High / Medium / Normal using a documented,
   deterministic rule table — NO LLM, no probabilities.
3. Apply a configurable waiting-time escalation rule.
4. Persist a decision document to agent_decisions.
5. Return a PriorityResult dataclass.

Rule Table (complete, no hidden logic elsewhere)
------------------------------------------------
The base priority is determined solely by (urgency × medical_type):

    URGENCY     | MEDICAL_TYPE                            | BASE PRIORITY
    ------------|------------------------------------------|---------------
    CRITICAL    | Blood, Organs, Emergency Medicine        | Critical
    CRITICAL    | Plasma, Vaccines, Insulin, Other         | High
    HIGH        | Blood, Organs, Emergency Medicine, Plasma| High
    HIGH        | Vaccines, Insulin, Other                 | High
    MEDIUM      | Blood, Organs                            | High
    MEDIUM      | Emergency Medicine, Plasma               | Medium
    MEDIUM      | Vaccines, Insulin, Other                 | Medium
    LOW         | Any                                      | Normal

Escalation rule (configurable via settings.PRIORITY_ESCALATION_MINUTES):
    If (now - created_at) > PRIORITY_ESCALATION_MINUTES:
        Normal  → Medium
        Medium  → High
        High    → Critical
        Critical stays Critical

Priority tier ordering (ascending): Normal < Medium < High < Critical

Failure semantics
-----------------
The agent never raises. If input is malformed, the result is priority=Normal
with a reason explaining the failure, and a decision is still persisted.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any, Optional

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

# ── Priority tier ordering ────────────────────────────────────────────────────

_TIERS = ["Normal", "Medium", "High", "Critical"]


def _tier_index(tier: str) -> int:
    """Return the numeric index of a tier (higher = more urgent)."""
    return _TIERS.index(tier)


def _bump_tier(tier: str) -> str:
    """Escalate one tier level. Critical stays Critical."""
    idx = _tier_index(tier)
    return _TIERS[min(idx + 1, len(_TIERS) - 1)]


# ── Base priority lookup table ────────────────────────────────────────────────
# Keys are (urgency_upper, medical_type_value).
# This table encodes the entire rule set — nothing is scattered in logic.

_BASE_PRIORITY: dict[tuple[str, str], str] = {
    # CRITICAL urgency
    ("CRITICAL", "Blood"):              "Critical",
    ("CRITICAL", "Organs"):             "Critical",
    ("CRITICAL", "Emergency Medicine"): "Critical",
    ("CRITICAL", "Plasma"):             "High",
    ("CRITICAL", "Vaccines"):           "High",
    ("CRITICAL", "Insulin"):            "High",
    ("CRITICAL", "Other"):              "High",
    # HIGH urgency
    ("HIGH", "Blood"):              "High",
    ("HIGH", "Organs"):             "High",
    ("HIGH", "Emergency Medicine"): "High",
    ("HIGH", "Plasma"):             "High",
    ("HIGH", "Vaccines"):           "High",
    ("HIGH", "Insulin"):            "High",
    ("HIGH", "Other"):              "High",
    # MEDIUM urgency
    ("MEDIUM", "Blood"):              "High",
    ("MEDIUM", "Organs"):             "High",
    ("MEDIUM", "Emergency Medicine"): "Medium",
    ("MEDIUM", "Plasma"):             "Medium",
    ("MEDIUM", "Vaccines"):           "Medium",
    ("MEDIUM", "Insulin"):            "Medium",
    ("MEDIUM", "Other"):              "Medium",
    # LOW urgency — always Normal regardless of type
    ("LOW", "Blood"):              "Normal",
    ("LOW", "Organs"):             "Normal",
    ("LOW", "Emergency Medicine"): "Normal",
    ("LOW", "Plasma"):             "Normal",
    ("LOW", "Vaccines"):           "Normal",
    ("LOW", "Insulin"):            "Normal",
    ("LOW", "Other"):              "Normal",
}

_PRIORITY_SCORES: dict[str, float] = {
    "Critical": 1.00,
    "High":     0.75,
    "Medium":   0.50,
    "Normal":   0.25,
}


def classify_priority(request: dict, now: datetime | None = None) -> tuple[str, float]:
    """
    Classify a medical request's dispatch priority without side effects (no DB logging).
    Returns (priority_tier, priority_score).
    """
    if now is None:
        now = datetime.now(UTC)
    try:
        urgency_raw = request.get("urgency", "")
        urgency: str = (urgency_raw.value if hasattr(urgency_raw, "value") else str(urgency_raw)).upper()
        med_type_raw = request.get("medical_type", "")
        medical_type: str = med_type_raw.value if hasattr(med_type_raw, "value") else str(med_type_raw)
        created_at: datetime = request.get("created_at", now)
    except Exception:
        return "Normal", _PRIORITY_SCORES["Normal"]

    if hasattr(created_at, "tzinfo") and created_at.tzinfo is None:
        created_at = created_at.replace(tzinfo=UTC)
    elif not hasattr(created_at, "tzinfo"):
        created_at = now

    waiting_minutes = (now - created_at).total_seconds() / 60.0
    base_priority = _BASE_PRIORITY.get((urgency, medical_type), "Medium")
    escalation_threshold = settings.PRIORITY_ESCALATION_MINUTES

    final_priority = base_priority
    if waiting_minutes > escalation_threshold and base_priority != "Critical":
        final_priority = _bump_tier(base_priority)

    tier_score = _PRIORITY_SCORES.get(final_priority, 0.25)
    return final_priority, tier_score


# ── Result dataclass ──────────────────────────────────────────────────────────

@dataclass
class PriorityResult:
    priority: str           # "Critical" | "High" | "Medium" | "Normal"
    reason: str             # Human-readable explanation of the decision
    decision_id: str        # UUID of the agent_decisions document
    escalated: bool = False  # True if waiting-time rule bumped the tier
    score: float = 0.0      # Priority score in [0.25, 1.00]


# ── Agent ─────────────────────────────────────────────────────────────────────

class PriorityAgent:
    """
    Stateless, deterministic priority classifier.

    Parameters
    ----------
    decision_repo : AgentDecisionRepository (injectable for testing).
    """

    def __init__(self, decision_repo: Any) -> None:
        self._repo = decision_repo

    async def run(self, request: dict) -> PriorityResult:
        """
        Classify a medical request's dispatch priority.

        Parameters
        ----------
        request : raw MongoDB document from the medical_requests collection.

        Returns
        -------
        PriorityResult — never raises.
        """
        decision_id = str(uuid.uuid4())
        now = datetime.now(UTC)

        # ── Extract input fields ──────────────────────────────────────────────
        try:
            urgency: str = str(request.get("urgency", "")).upper()
            medical_type: str = str(request.get("medical_type", ""))
            created_at: datetime = request.get("created_at", now)
            request_id: str = str(request.get("request_id", request.get("id", "")))
        except Exception as exc:
            reason = f"Input extraction failed: {exc}"
            log.error("priority_agent_input_error", error=str(exc))
            return await self._persist_and_return(
                decision_id=decision_id,
                request_id="unknown",
                priority="Normal",
                escalated=False,
                reason=reason,
                input_snapshot=request,
                timestamp=now,
            )

        # ── Ensure created_at is timezone-aware ───────────────────────────────
        if created_at.tzinfo is None:
            created_at = created_at.replace(tzinfo=UTC)

        waiting_minutes = (now - created_at).total_seconds() / 60.0

        # ── Step 1: Lookup base priority ──────────────────────────────────────
        base_priority = _BASE_PRIORITY.get((urgency, medical_type))
        if base_priority is None:
            # Unrecognised combination — default to Medium and log it
            base_priority = "Medium"
            log.warning(
                "priority_agent_unknown_combination",
                urgency=urgency,
                medical_type=medical_type,
            )

        # ── Step 2: Apply escalation rule ─────────────────────────────────────
        escalated = False
        final_priority = base_priority
        escalation_threshold = settings.PRIORITY_ESCALATION_MINUTES

        if waiting_minutes > escalation_threshold and base_priority != "Critical":
            final_priority = _bump_tier(base_priority)
            escalated = (final_priority != base_priority)

        # ── Step 3: Build reason string ───────────────────────────────────────
        reason_parts = [
            f"urgency={urgency}, medical_type={medical_type!r}",
            f"base_priority={base_priority}",
        ]
        if escalated:
            reason_parts.append(
                f"escalated {base_priority}→{final_priority} "
                f"(waited {waiting_minutes:.1f}m > {escalation_threshold}m threshold)"
            )
        reason = "; ".join(reason_parts)

        log.info(
            "priority_agent_decision",
            request_id=request_id,
            priority=final_priority,
            escalated=escalated,
            waiting_minutes=round(waiting_minutes, 1),
        )

        return await self._persist_and_return(
            decision_id=decision_id,
            request_id=request_id,
            priority=final_priority,
            escalated=escalated,
            reason=reason,
            input_snapshot={
                "urgency": urgency,
                "medical_type": medical_type,
                "waiting_minutes": round(waiting_minutes, 2),
                "quantity": request.get("quantity"),
                "weight_kg": request.get("weight_kg"),
            },
            timestamp=now,
        )

    # ── Private helpers ───────────────────────────────────────────────────────

    async def _persist_and_return(
        self,
        *,
        decision_id: str,
        request_id: str,
        priority: str,
        escalated: bool,
        reason: str,
        input_snapshot: dict,
        timestamp: datetime,
    ) -> PriorityResult:
        """Persist the decision and return the dataclass. Swallows storage errors."""
        tier_score = _PRIORITY_SCORES.get(priority, 0.25)
        try:
            await self._repo.create({
                "decision_id": decision_id,
                "agent_name": "PriorityAgent",
                "request_id": request_id,
                "decision": priority,
                "score": None,          # PriorityAgent uses rule-based tiers in decision repo
                "reason": reason,
                "input_snapshot": input_snapshot,
                "timestamp": timestamp,
            })
        except Exception as exc:
            log.error(
                "priority_agent_persist_error",
                decision_id=decision_id,
                error=str(exc),
            )

        return PriorityResult(
            priority=priority,
            reason=reason,
            decision_id=decision_id,
            escalated=escalated,
            score=tier_score,
        )
