# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""
degradation_model.py — Nanofluid Property Degradation and Lifecycle Engine
GlacierEQ APEX Stack | APEX Architecture

Tracks exponential thermal conductivity decay of nanofluid batches
through their operational lifespan and schedules replacement events.

Decay model:
  k(t) = k_fresh * exp(-lambda * t)
  where lambda = ln(2) / half_life_days

Lifecycle states per batch:
  active -> degradation_warning -> replacement_due -> replacement_scheduled -> retired

Scheduling policy:
  - degradation_warning:  conductivity_factor < 0.90 (10% loss)
  - replacement_due:      conductivity_factor < 0.85 (15% loss — README invariant)
  - replacement_scheduled: replacement event created, awaiting maintenance window
  - retired:              old batch drained, new batch activated

Batch lifecycle is immutable once retired; all history is preserved
for audit trail per BatchChangeEvent schema.
"""

from dataclasses import dataclass, field
from typing import List, Optional, Dict
import math
import datetime
import logging
import uuid


logger = logging.getLogger("degradation_model")

DEGRADATION_WARNING_THRESHOLD = 0.90
REPLACEMENT_DUE_THRESHOLD = 0.85
RETENTION_PERIOD_DAYS = 365

LIFECYCLE_STATES = (
    "active",
    "degradation_warning",
    "replacement_due",
    "replacement_scheduled",
    "retired",
)


@dataclass
class DegradationRecord:
    """Immutable snapshot of a batch's conductivity at a point in time."""
    timestamp: str
    age_days: int
    measured_conductivity_w_mk: Optional[float]
    conductivity_factor: float
    lifecycle_state: str


@dataclass
class ReplacementEvent:
    """Scheduled or completed replacement action for a degraded batch."""
    event_id: str
    circuit_id: str
    old_batch_id: str
    new_batch_id: Optional[str]
    reason: str
    scheduled_date: str
    completed_date: Optional[str] = None
    operator: Optional[str] = None
    conductivity_before: Optional[float] = None
    conductivity_after: Optional[float] = None


@dataclass
class BatchLifecycle:
    """
    Full lifecycle tracker for a single nanofluid batch.

    Tracks conductivity decay from fresh state, emits lifecycle transitions,
    and generates replacement events when thresholds are breached.
    """
    batch_id: str
    circuit_id: str
    nanoparticle: str
    half_life_days: float
    fresh_conductivity_w_mk: float
    install_date: str
    age_days: int = 0
    lifecycle_state: str = "active"
    measurements: List[DegradationRecord] = field(default_factory=list)
    replacement_events: List[ReplacementEvent] = field(default_factory=list)
    _idempotency_guard: set = field(default_factory=set, repr=False)

    def conductivity_factor(self, age_days: Optional[int] = None) -> float:
        """
        Exponential decay of thermal conductivity at given age.

        factor = exp(-ln(2) * age / half_life)
        Returns 0.0–1.0 where 1.0 = fresh fluid.
        """
        t = age_days if age_days is not None else self.age_days
        if t < 0:
            raise ValueError(f"age_days must be non-negative, got {t}")
        if self.half_life_days <= 0:
            raise ValueError(f"half_life_days must be positive, got {self.half_life_days}")
        decay_constant = math.log(2) / self.half_life_days
        return math.exp(-decay_constant * t)

    def effective_conductivity(self, age_days: Optional[int] = None) -> float:
        """Absolute conductivity after decay: k_fresh * factor."""
        return self.fresh_conductivity_w_mk * self.conductivity_factor(age_days)

    def days_until_replacement(self) -> float:
        """
        Days from now until conductivity_factor drops below REPLACEMENT_DUE_THRESHOLD.
        Returns 0.0 if already past threshold. Negative means overdue.
        """
        factor = self.conductivity_factor()
        if factor <= REPLACEMENT_DUE_THRESHOLD:
            return 0.0
        decay_constant = math.log(2) / self.half_life_days
        target_age = -math.log(REPLACEMENT_DUE_THRESHOLD) / decay_constant
        return max(0.0, target_age - self.age_days)

    def advance_days(self, delta_days: int) -> Dict[str, object]:
        """
        Advance the batch clock by delta_days. Records measurement,
        evaluates lifecycle transition, emits replacement event if needed.

        Returns dict with transition info for observability.
        """
        if delta_days < 0:
            raise ValueError(f"delta_days must be non-negative, got {delta_days}")

        self.age_days += delta_days
        factor = self.conductivity_factor()

        record = DegradationRecord(
            timestamp=datetime.datetime.utcnow().isoformat() + "Z",
            age_days=self.age_days,
            measured_conductivity_w_mk=round(self.effective_conductivity(), 4),
            conductivity_factor=round(factor, 6),
            lifecycle_state=self.lifecycle_state,
        )
        self.measurements.append(record)

        previous_state = self.lifecycle_state
        new_state = self._evaluate_lifecycle_transition(factor)

        transition = {"from": previous_state, "to": new_state, "factor": factor, "age_days": self.age_days}
        if new_state != previous_state:
            self.lifecycle_state = new_state
            logger.info(
                "lifecycle_transition batch=%s circuit=%s from=%s to=%s factor=%.4f age=%d",
                self.batch_id, self.circuit_id, previous_state, new_state, factor, self.age_days,
            )
            if new_state == "replacement_due" and self.batch_id not in self._idempotency_guard:
                self._emit_replacement_event("degradation")
                self._idempotency_guard.add(self.batch_id)

        return transition

    def _evaluate_lifecycle_transition(self, factor: float) -> str:
        """Pure function: factor + current state -> new state."""
        if self.lifecycle_state == "retired":
            return "retired"
        if self.lifecycle_state == "replacement_scheduled":
            return "replacement_scheduled"
        if factor <= REPLACEMENT_DUE_THRESHOLD:
            return "replacement_due"
        if factor <= DEGRADATION_WARNING_THRESHOLD:
            return "degradation_warning"
        return "active"

    def _emit_replacement_event(self, reason: str) -> ReplacementEvent:
        event = ReplacementEvent(
            event_id=str(uuid.uuid4()),
            circuit_id=self.circuit_id,
            old_batch_id=self.batch_id,
            new_batch_id=None,
            reason=reason,
            scheduled_date=datetime.datetime.utcnow().isoformat() + "Z",
        )
        self.replacement_events.append(event)
        logger.warning(
            "replacement_triggered batch=%s circuit=%s reason=%s",
            self.batch_id, self.circuit_id, reason,
        )
        return event

    def retire(self, new_batch_id: str, operator: str) -> None:
        """Mark batch as retired and link to replacement batch."""
        self.lifecycle_state = "retired"
        if self.replacement_events:
            last = self.replacement_events[-1]
            last.new_batch_id = new_batch_id
            last.completed_date = datetime.datetime.utcnow().isoformat() + "Z"
            last.operator = operator
        logger.info(
            "batch_retired batch=%s new_batch=%s operator=%s",
            self.batch_id, new_batch_id, operator,
        )

    def to_dict(self) -> dict:
        """Serialise for circuit_manifest consumption."""
        return {
            "batch_id": self.batch_id,
            "circuit_id": self.circuit_id,
            "nanoparticle": self.nanoparticle,
            "half_life_days": self.half_life_days,
            "fresh_conductivity_w_mk": self.fresh_conductivity_w_mk,
            "install_date": self.install_date,
            "age_days": self.age_days,
            "conductivity_factor": round(self.conductivity_factor(), 6),
            "effective_conductivity_w_mk": round(self.effective_conductivity(), 4),
            "lifecycle_state": self.lifecycle_state,
            "days_until_replacement": round(self.days_until_replacement(), 1),
            "measurement_count": len(self.measurements),
            "replacement_event_count": len(self.replacement_events),
        }


@dataclass
class FleetLifecycleManager:
    """
    Manages lifecycle of all batch instances across circuits.
    Provides fleet-wide replacement scheduling and audit reporting.
    """
    batches: Dict[str, BatchLifecycle] = field(default_factory=dict)

    def register_batch(self, batch: BatchLifecycle) -> None:
        if batch.batch_id in self.batches:
            raise ValueError(f"Duplicate batch_id: {batch.batch_id}")
        self.batches[batch.batch_id] = batch
        logger.info("batch_registered batch=%s circuit=%s", batch.batch_id, batch.circuit_id)

    def advance_all(self, delta_days: int) -> List[Dict[str, object]]:
        """Advance all active batches and return transition events."""
        transitions = []
        for batch in self.batches.values():
            if batch.lifecycle_state not in ("active", "degradation_warning", "replacement_due"):
                continue
            t = batch.advance_days(delta_days)
            transitions.append({"batch_id": batch.batch_id, **t})
        return transitions

    def pending_replacements(self) -> List[BatchLifecycle]:
        """Batches that need replacement — ready for maintenance scheduling."""
        return [
            b for b in self.batches.values()
            if b.lifecycle_state == "replacement_due"
        ]

    def fleet_health_report(self) -> dict:
        """Aggregate fleet status for cooling ops dashboard."""
        state_counts: Dict[str, int] = {}
        for batch in self.batches.values():
            state_counts[batch.lifecycle_state] = state_counts.get(batch.lifecycle_state, 0) + 1

        due_soon = [
            b.to_dict() for b in self.batches.values()
            if b.lifecycle_state in ("active", "degradation_warning")
            and b.days_until_replacement() < 30
        ]

        return {
            "total_batches": len(self.batches),
            "state_counts": state_counts,
            "replacement_due_count": len(self.pending_replacements()),
            "replacement_due_soon": due_soon,
        }

    def export_manifest(self, path: str = "integration/circuit_manifest.json") -> dict:
        """Export full fleet state for cooling orchestrator consumption."""
        import json
        manifest = {
            "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
            "fleet_health": self.fleet_health_report(),
            "batches": [b.to_dict() for b in self.batches.values()],
        }
        with open(path, "w") as f:
            json.dump(manifest, f, indent=2)
        logger.info("manifest_exported path=%s batches=%d", path, len(self.batches))
        return manifest
