"""
circuit_optimizer.py — Multi-Objective Blend Selection Engine
GlacierEQ Sovereign Stack | APEX Architecture

Selects the optimal nanofluid blend for a given Colossus 2 cooling circuit
by balancing four competing objectives:

  1. Thermal enhancement (conductivity gain, % vs base fluid) — maximize
  2. Pump energy penalty (viscosity-driven power increase) — minimize
  3. Fluid stability (zeta potential, particle size, age risk) — maximize
  4. Replacement interval cost (degradation half-life, circuit downtime) — maximize

The composite score uses a weighted linear combination:
  score = w_thermal * enh - w_pump * pump_penalty + w_stability * stability - w_replace * replace_cost

Default weights reflect Colossus 2 priority order:
  thermal > stability > pump > replacement
  (0.40, 0.30, 0.20, 0.10)

Outputs a ranked list of CandidateResult objects, one per blend evaluated.
The top-ranked candidate is the operational recommendation.
"""

from dataclasses import dataclass, field
from typing import List, Optional
import json
import datetime

from nanosphere_model import (
    NanofluidSpec,
    enhancement_pct,
    NANOPARTICLE_CONDUCTIVITY,
    BASE_FLUID_CONDUCTIVITY,
    DEGRADATION_HALFLIFE,
)
from viscosity_model import ViscositySpec, pump_penalty_pct, evaluate as viscosity_evaluate
from stability_model import StabilitySpec, evaluate as stability_evaluate


# Default objective weights — must sum to 1.0
DEFAULT_WEIGHTS = {
    "thermal":     0.40,
    "stability":   0.30,
    "pump":        0.20,
    "replacement": 0.10,
}

# Normalization caps for scoring
MAX_ENHANCEMENT_PCT  = 50.0   # >50% gain is treated as 50 for scoring
MAX_PUMP_PENALTY_PCT = 40.0   # >40% penalty is treated as 40 (floor score)
MAX_STABILITY_SCORE  = 100.0
MAX_HALFLIFE_DAYS    = 200.0  # SiC ~200 days; normalize to this


@dataclass
class CircuitRequirements:
    """Input constraints from the cooling circuit operator."""
    circuit_id: str
    base_fluid: str = "water"
    min_enhancement_pct: float = 10.0      # Minimum acceptable thermal gain
    max_pump_penalty_pct: float = 25.0     # Hard ceiling on pump energy increase
    max_volume_fraction: float = 0.05      # 5% default ceiling
    min_stability_score: float = 60.0      # Must be "monitor" or better
    min_halflife_days: int = 90            # Minimum replacement interval
    temperature_c: float = 40.0            # Circuit operating temperature
    particle_shape: str = "sphere"
    target_zeta_mv: float = 35.0           # Assumed zeta for new fluid batches


@dataclass
class CandidateResult:
    rank: int
    name: str
    nanoparticle: str
    volume_fraction_pct: float
    enhancement_pct: float
    pump_penalty_pct: float
    stability_score: float
    stability_status: str
    halflife_days: int
    composite_score: float
    disqualified: bool = False
    disqualify_reason: Optional[str] = None
    recommended: bool = False


def _normalize(value: float, min_val: float, max_val: float) -> float:
    """Normalize a value to [0, 1] clamped."""
    if max_val == min_val:
        return 0.0
    return max(0.0, min(1.0, (value - min_val) / (max_val - min_val)))


def score_candidate(
    spec: NanofluidSpec,
    requirements: CircuitRequirements,
    weights: dict = None,
    zeta_mv: float = 35.0,
    age_days: int = 0,
) -> CandidateResult:
    """Evaluate a single candidate blend against circuit requirements."""
    if weights is None:
        weights = DEFAULT_WEIGHTS

    enh = enhancement_pct(spec)
    v_spec = ViscositySpec(
        base_fluid=spec.base_fluid,
        volume_fraction=spec.volume_fraction,
        temperature_c=spec.temperature_c,
    )
    pump = pump_penalty_pct(v_spec)

    s_spec = StabilitySpec(
        nanoparticle=spec.nanoparticle,
        base_fluid=spec.base_fluid,
        volume_fraction=spec.volume_fraction,
        particle_size_nm=30.0,
        zeta_mv=zeta_mv,
        age_days=age_days,
        temperature_c=spec.temperature_c,
    )
    stab_result = stability_evaluate(s_spec)
    halflife = DEGRADATION_HALFLIFE.get(spec.nanoparticle, 120)

    # Disqualification checks (hard constraints)
    disqualified = False
    disqualify_reason = None
    if enh < requirements.min_enhancement_pct:
        disqualified = True
        disqualify_reason = f"Enhancement {enh:.1f}% below minimum {requirements.min_enhancement_pct}%"
    elif pump > requirements.max_pump_penalty_pct:
        disqualified = True
        disqualify_reason = f"Pump penalty {pump:.1f}% exceeds hard ceiling {requirements.max_pump_penalty_pct}%"
    elif stab_result.stability_score < requirements.min_stability_score:
        disqualified = True
        disqualify_reason = f"Stability score {stab_result.stability_score} below minimum {requirements.min_stability_score}"
    elif halflife < requirements.min_halflife_days:
        disqualified = True
        disqualify_reason = f"Half-life {halflife} days below minimum {requirements.min_halflife_days} days"

    # Composite score (even for disqualified — useful for gap analysis)
    n_thermal   = _normalize(enh, 0.0, MAX_ENHANCEMENT_PCT)
    n_pump      = _normalize(MAX_PUMP_PENALTY_PCT - pump, 0.0, MAX_PUMP_PENALTY_PCT)  # inverted
    n_stability = _normalize(stab_result.stability_score, 0.0, MAX_STABILITY_SCORE)
    n_replace   = _normalize(halflife, 0.0, MAX_HALFLIFE_DAYS)

    composite = (
        weights["thermal"]     * n_thermal +
        weights["stability"]   * n_stability +
        weights["pump"]        * n_pump +
        weights["replacement"] * n_replace
    )

    return CandidateResult(
        rank=0,  # assigned after sorting
        name=spec.name,
        nanoparticle=spec.nanoparticle,
        volume_fraction_pct=round(spec.volume_fraction * 100, 2),
        enhancement_pct=round(enh, 2),
        pump_penalty_pct=round(pump, 2),
        stability_score=stab_result.stability_score,
        stability_status=stab_result.status,
        halflife_days=halflife,
        composite_score=round(composite, 4),
        disqualified=disqualified,
        disqualify_reason=disqualify_reason,
    )


def rank_blends(
    requirements: CircuitRequirements,
    weights: dict = None,
    zeta_mv: float = 35.0,
    age_days: int = 0,
) -> List[CandidateResult]:
    """
    Evaluate all particle + volume fraction combinations against requirements.
    Returns ranked list; first qualifying candidate is marked as recommended.
    """
    if weights is None:
        weights = DEFAULT_WEIGHTS

    candidates = []
    volume_fractions = [0.005, 0.01, 0.015, 0.02, 0.025, 0.03, 0.04, 0.05]

    for particle in NANOPARTICLE_CONDUCTIVITY:
        for phi in volume_fractions:
            if phi > requirements.max_volume_fraction:
                continue
            spec = NanofluidSpec(
                name=f"{particle}_{int(phi*100)}pct",
                base_fluid=requirements.base_fluid,
                nanoparticle=particle,
                volume_fraction=phi,
                particle_size_nm=30.0,
                particle_shape=requirements.particle_shape,
                temperature_c=requirements.temperature_c,
                circuit_id=requirements.circuit_id,
            )
            result = score_candidate(spec, requirements, weights, zeta_mv, age_days)
            candidates.append(result)

    # Sort: qualified first by composite_score desc, then disqualified by composite_score desc
    qualified   = sorted([c for c in candidates if not c.disqualified],
                         key=lambda x: x.composite_score, reverse=True)
    disqualified = sorted([c for c in candidates if c.disqualified],
                          key=lambda x: x.composite_score, reverse=True)

    ranked = qualified + disqualified
    for i, c in enumerate(ranked):
        c.rank = i + 1

    if qualified:
        qualified[0].recommended = True

    return ranked


def export_recommendation(
    requirements: CircuitRequirements,
    results: List[CandidateResult],
    path: str = "integration/circuit_manifest.json",
) -> dict:
    """Export top recommendation and full ranked table as circuit manifest."""
    top = next((c for c in results if c.recommended), None)
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "circuit_id": requirements.circuit_id,
        "base_fluid": requirements.base_fluid,
        "recommendation": {
            "name": top.name if top else None,
            "nanoparticle": top.nanoparticle if top else None,
            "volume_fraction_pct": top.volume_fraction_pct if top else None,
            "enhancement_pct": top.enhancement_pct if top else None,
            "pump_penalty_pct": top.pump_penalty_pct if top else None,
            "stability_status": top.stability_status if top else None,
            "halflife_days": top.halflife_days if top else None,
            "composite_score": top.composite_score if top else None,
        } if top else None,
        "top_10": [
            {
                "rank": c.rank,
                "name": c.name,
                "enhancement_pct": c.enhancement_pct,
                "pump_penalty_pct": c.pump_penalty_pct,
                "stability_status": c.stability_status,
                "halflife_days": c.halflife_days,
                "composite_score": c.composite_score,
                "disqualified": c.disqualified,
                "disqualify_reason": c.disqualify_reason,
            }
            for c in results[:10]
        ],
    }
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    req = CircuitRequirements(
        circuit_id="CIRCUIT-01",
        base_fluid="water",
        min_enhancement_pct=12.0,
        max_pump_penalty_pct=20.0,
        max_volume_fraction=0.05,
        min_stability_score=65.0,
        min_halflife_days=100,
        temperature_c=40.0,
    )

    results = rank_blends(req)

    print(f"Top 5 blends for {req.circuit_id}:")
    for c in results[:5]:
        flag = "[RECOMMENDED]" if c.recommended else ""
        dq   = f"[DQ: {c.disqualify_reason}]" if c.disqualified else ""
        print(f"  #{c.rank} {c.name:30s}  "
              f"enh={c.enhancement_pct:5.1f}%  "
              f"pump+{c.pump_penalty_pct:4.1f}%  "
              f"stab={c.stability_status:9s}  "
              f"hl={c.halflife_days}d  "
              f"score={c.composite_score:.3f}  {flag}{dq}")
