"""
stability_model.py — Nanofluid Stability and Sedimentation Risk Engine
GlacierEQ APEX Stack | APEX Architecture

Tracks colloidal stability of nanofluid suspensions using:
  - Zeta potential proxy (electrostatic repulsion between particles)
  - Particle size / sedimentation velocity (Stokes settling)
  - Volume fraction agglomeration risk
  - Age-dependent aggregation drift

Outputs a 0–100 stability score and an operational status:
  stable (≥80) | monitor (60–79) | degrading (40–59) | unstable (<40)

Key references:
  - DLVO theory: zeta > 30 mV = stable, < 15 mV = rapid flocculation
  - Stokes' law settling velocity for particle sedimentation rate
  - Typical circuit window: 90–200 days depending on nanoparticle type
"""

from dataclasses import dataclass, field
from typing import Optional, List
import math


# Particle density (kg/m³) for sedimentation calculation
PARTICLE_DENSITY_KG_M3 = {
    "Al2O3":    3970.0,
    "TiO2":     4230.0,
    "CuO":      6310.0,
    "graphene": 2200.0,
    "SiC":      3210.0,
    "ZnO":      5600.0,
    "Fe3O4":    5180.0,
}

# Fluid density (kg/m³) at ~30°C
FLUID_DENSITY_KG_M3 = {
    "water":            996.0,
    "ethylene_glycol":  1110.0,
    "water_eg_50_50":   1058.0,
    "propylene_glycol": 1032.0,
    "engine_oil":       870.0,
}

# Zeta potential stability thresholds (mV, absolute value)
ZETA_STABLE_MV    = 35.0   # |zeta| > 35 mV: stable
ZETA_MONITOR_MV   = 25.0   # 25–35 mV: monitor
ZETA_DEGRADING_MV = 15.0   # 15–25 mV: degrading (aggregation risk)
                            # < 15 mV: rapid flocculation / unstable

# Maximum "safe" particle size for circuit operation (nm)
# Above this, sedimentation becomes operationally significant
MAX_SAFE_PARTICLE_NM = 100.0

# Age drift rate: score penalty per day from aggregation growth
AGE_PENALTY_PER_DAY = 0.12   # max 20 points over ~167 days
MAX_AGE_PENALTY     = 20.0


@dataclass
class StabilitySpec:
    nanoparticle: str
    base_fluid: str
    volume_fraction: float          # 0.0 – 0.10
    particle_size_nm: float         # Primary particle size
    zeta_mv: float                  # Measured or estimated |zeta potential| in mV
    age_days: int = 0
    temperature_c: float = 30.0
    circuit_id: Optional[str] = None
    batch_id: Optional[str] = None


@dataclass
class StabilityResult:
    spec: StabilitySpec
    stability_score: float          # 0–100
    status: str                     # stable | monitor | degrading | unstable
    stokes_velocity_nm_s: float     # Settling velocity in nm/s
    estimated_shelf_days: float     # Days until score drops below 60 (monitor threshold)
    risk_factors: List[str] = field(default_factory=list)
    replacement_recommended: bool = False


def stokes_settling_velocity(spec: StabilitySpec) -> float:
    """
    Stokes settling velocity (nm/s) for a spherical particle.

    v_s = (2 * r² * (rho_p - rho_f) * g) / (9 * mu)

    Returns nm/s for operationally meaningful units.
    NOTE: this is the single-particle limit; real suspensions
    settle faster due to hindered settling at phi > 1%.
    """
    r_m = (spec.particle_size_nm * 1e-9) / 2.0
    rho_p = PARTICLE_DENSITY_KG_M3.get(spec.nanoparticle, 4000.0)
    rho_f = FLUID_DENSITY_KG_M3.get(spec.base_fluid, 1000.0)
    g = 9.81  # m/s²
    # Approximate dynamic viscosity in Pa·s from cP: water ~0.00089 at 25°C
    # Use simple temperature-adjusted estimate
    mu_pas = 0.00089 * max(0.35, 1.0 - 0.02 * (spec.temperature_c - 25.0))

    v_ms = (2.0 * r_m**2 * (rho_p - rho_f) * g) / (9.0 * mu_pas)
    return v_ms * 1e9  # convert m/s to nm/s


def stability_score(spec: StabilitySpec) -> float:
    """Composite 0–100 stability score. Higher = more stable."""
    score = 100.0
    risk_factors = []

    # Zeta potential deduction (largest driver)
    zeta = abs(spec.zeta_mv)
    if zeta < ZETA_DEGRADING_MV:
        score -= 40.0
    elif zeta < ZETA_MONITOR_MV:
        score -= 25.0
    elif zeta < ZETA_STABLE_MV:
        score -= 10.0

    # Particle size deduction
    if spec.particle_size_nm > MAX_SAFE_PARTICLE_NM:
        score -= 20.0
    elif spec.particle_size_nm > 60.0:
        score -= 8.0

    # Volume fraction agglomeration risk
    if spec.volume_fraction > 0.07:
        score -= 20.0
    elif spec.volume_fraction > 0.05:
        score -= 12.0
    elif spec.volume_fraction > 0.03:
        score -= 5.0

    # Age-dependent aggregation drift
    age_penalty = min(spec.age_days * AGE_PENALTY_PER_DAY, MAX_AGE_PENALTY)
    score -= age_penalty

    return max(round(score, 1), 0.0)


def stability_status(score: float) -> str:
    if score >= 80.0:
        return "stable"
    if score >= 60.0:
        return "monitor"
    if score >= 40.0:
        return "degrading"
    return "unstable"


def estimated_shelf_days(spec: StabilitySpec) -> float:
    """
    Estimate days from NOW until stability_score drops below 60 (monitor threshold).
    Solve: score_at_day_X = stability_score(age=0) - X * AGE_PENALTY_PER_DAY = 60
    """
    base_score = stability_score(
        StabilitySpec(
            nanoparticle=spec.nanoparticle,
            base_fluid=spec.base_fluid,
            volume_fraction=spec.volume_fraction,
            particle_size_nm=spec.particle_size_nm,
            zeta_mv=spec.zeta_mv,
            age_days=0,
            temperature_c=spec.temperature_c,
        )
    )
    if base_score <= 60.0:
        return 0.0
    remaining_margin = base_score - 60.0
    return round(remaining_margin / AGE_PENALTY_PER_DAY, 1)


def evaluate(spec: StabilitySpec) -> StabilityResult:
    """Full stability evaluation with risk factors and replacement flag."""
    score = stability_score(spec)
    status = stability_status(score)
    v_settle = stokes_settling_velocity(spec)
    shelf = estimated_shelf_days(spec)
    risk_factors = []

    if abs(spec.zeta_mv) < ZETA_STABLE_MV:
        risk_factors.append(f"Low zeta potential ({spec.zeta_mv:.1f} mV) — electrostatic repulsion marginal")
    if spec.particle_size_nm > MAX_SAFE_PARTICLE_NM:
        risk_factors.append(f"Particle size {spec.particle_size_nm:.0f} nm exceeds {MAX_SAFE_PARTICLE_NM:.0f} nm safe limit")
    if spec.volume_fraction > 0.05:
        risk_factors.append(f"Volume fraction {spec.volume_fraction*100:.1f}% above 5% agglomeration threshold")
    if spec.age_days > 90:
        risk_factors.append(f"Fluid age {spec.age_days} days — verify conductivity measurement")
    if v_settle > 50.0:
        risk_factors.append(f"Stokes settling velocity {v_settle:.1f} nm/s — flow interruption risk")

    replacement_recommended = status in ("degrading", "unstable")

    return StabilityResult(
        spec=spec,
        stability_score=score,
        status=status,
        stokes_velocity_nm_s=round(v_settle, 3),
        estimated_shelf_days=shelf,
        risk_factors=risk_factors,
        replacement_recommended=replacement_recommended,
    )


if __name__ == "__main__":
    spec = StabilitySpec(
        nanoparticle="Al2O3",
        base_fluid="water",
        volume_fraction=0.03,
        particle_size_nm=30.0,
        zeta_mv=38.0,
        age_days=27,
        circuit_id="CIRCUIT-01",
    )
    result = evaluate(spec)
    print(f"Stability score: {result.stability_score}")
    print(f"Status: {result.status}")
    print(f"Stokes settling: {result.stokes_velocity_nm_s} nm/s")
    print(f"Estimated shelf remaining: {result.estimated_shelf_days} days")
    if result.risk_factors:
        print("Risk factors:")
        for r in result.risk_factors:
            print(f"  - {r}")
    print(f"Replacement recommended: {result.replacement_recommended}")
