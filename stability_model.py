"""Bounded nanofluid stability and settling-risk scenario model.

Thresholds and coefficients are explicit portfolio assumptions. Outputs are
comparative estimates, not laboratory measurements or maintenance instructions.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field

from nanosphere_model import (
    BASE_FLUID_CONDUCTIVITY,
    NANOPARTICLE_CONDUCTIVITY,
    NanofluidInputError,
)


PARTICLE_DENSITY_KG_M3 = {
    "Al2O3": 3970.0,
    "TiO2": 4230.0,
    "CuO": 6310.0,
    "graphene": 2200.0,
    "SiC": 3210.0,
    "ZnO": 5600.0,
    "Fe3O4": 5180.0,
}

FLUID_DENSITY_KG_M3 = {
    "water": 996.0,
    "ethylene_glycol": 1110.0,
    "water_eg_50_50": 1058.0,
    "propylene_glycol": 1032.0,
    "engine_oil": 870.0,
}

ZETA_STABLE_MV = 35.0
ZETA_MONITOR_MV = 25.0
ZETA_DEGRADING_MV = 15.0
MAX_SAFE_PARTICLE_NM = 100.0
AGE_PENALTY_PER_DAY = 0.12
MAX_AGE_PENALTY = 20.0


def _finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise NanofluidInputError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise NanofluidInputError(f"{name} must be finite")
    return numeric


@dataclass(frozen=True, slots=True)
class StabilitySpec:
    nanoparticle: str
    base_fluid: str
    volume_fraction: float
    particle_size_nm: float
    zeta_mv: float
    age_days: int = 0
    temperature_c: float = 30.0
    circuit_id: str | None = None
    batch_id: str | None = None

    def __post_init__(self) -> None:
        if self.nanoparticle not in NANOPARTICLE_CONDUCTIVITY:
            raise NanofluidInputError(f"unsupported nanoparticle: {self.nanoparticle}")
        if self.base_fluid not in BASE_FLUID_CONDUCTIVITY:
            raise NanofluidInputError(f"unsupported base_fluid: {self.base_fluid}")
        phi = _finite("volume_fraction", self.volume_fraction)
        if not 0.0 <= phi <= 0.10:
            raise NanofluidInputError("volume_fraction must be between 0.0 and 0.10")
        size = _finite("particle_size_nm", self.particle_size_nm)
        if size <= 0.0:
            raise NanofluidInputError("particle_size_nm must be greater than zero")
        _finite("zeta_mv", self.zeta_mv)
        _finite("temperature_c", self.temperature_c)
        if not isinstance(self.age_days, int) or isinstance(self.age_days, bool):
            raise NanofluidInputError("age_days must be an integer")
        if self.age_days < 0:
            raise NanofluidInputError("age_days cannot be negative")
        for field_name, value in (
            ("circuit_id", self.circuit_id),
            ("batch_id", self.batch_id),
        ):
            if value is not None and (not isinstance(value, str) or not value.strip()):
                raise NanofluidInputError(
                    f"{field_name} must be a non-empty string when provided"
                )


@dataclass(frozen=True, slots=True)
class StabilityResult:
    spec: StabilitySpec
    stability_score: float
    status: str
    stokes_velocity_nm_s: float
    estimated_remaining_days_to_monitor: float
    risk_factors: tuple[str, ...] = field(default_factory=tuple)
    replacement_review_recommended: bool = False


def approximate_base_viscosity_pas(spec: StabilitySpec) -> float:
    """Return a simple temperature-adjusted viscosity assumption for settling."""

    base_at_25 = {
        "water": 0.00089,
        "ethylene_glycol": 0.0161,
        "water_eg_50_50": 0.0034,
        "propylene_glycol": 0.0520,
        "engine_oil": 0.0860,
    }[spec.base_fluid]
    sensitivity = {
        "water": 0.020,
        "ethylene_glycol": 0.035,
        "water_eg_50_50": 0.027,
        "propylene_glycol": 0.045,
        "engine_oil": 0.060,
    }[spec.base_fluid]
    factor = max(0.35, 1.0 - sensitivity * (spec.temperature_c - 25.0))
    return base_at_25 * factor


def stokes_settling_velocity(spec: StabilitySpec) -> float:
    """Single-particle Stokes settling scenario in nm/s."""

    radius_m = (spec.particle_size_nm * 1e-9) / 2.0
    density_delta = (
        PARTICLE_DENSITY_KG_M3[spec.nanoparticle]
        - FLUID_DENSITY_KG_M3[spec.base_fluid]
    )
    viscosity_pas = approximate_base_viscosity_pas(spec)
    velocity_ms = (2.0 * radius_m**2 * density_delta * 9.81) / (
        9.0 * viscosity_pas
    )
    return max(velocity_ms * 1e9, 0.0)


def stability_score(spec: StabilitySpec) -> float:
    score = 100.0
    zeta = abs(spec.zeta_mv)
    if zeta < ZETA_DEGRADING_MV:
        score -= 40.0
    elif zeta < ZETA_MONITOR_MV:
        score -= 25.0
    elif zeta < ZETA_STABLE_MV:
        score -= 10.0

    if spec.particle_size_nm > MAX_SAFE_PARTICLE_NM:
        score -= 20.0
    elif spec.particle_size_nm > 60.0:
        score -= 8.0

    if spec.volume_fraction > 0.07:
        score -= 20.0
    elif spec.volume_fraction > 0.05:
        score -= 12.0
    elif spec.volume_fraction > 0.03:
        score -= 5.0

    score -= min(spec.age_days * AGE_PENALTY_PER_DAY, MAX_AGE_PENALTY)
    return max(round(score, 1), 0.0)


def stability_status(score: float) -> str:
    numeric = _finite("score", score)
    if not 0.0 <= numeric <= 100.0:
        raise NanofluidInputError("score must be between 0 and 100")
    if numeric >= 80.0:
        return "stable"
    if numeric >= 60.0:
        return "monitor"
    if numeric >= 40.0:
        return "degrading"
    return "unstable"


def estimated_remaining_days_to_monitor(spec: StabilitySpec) -> float:
    """Estimate scenario days until the score falls below 60 from current age."""

    current = stability_score(spec)
    if current <= 60.0:
        return 0.0
    if AGE_PENALTY_PER_DAY <= 0.0:
        return math.inf
    age_penalty_remaining = min(current - 60.0, MAX_AGE_PENALTY)
    return round(age_penalty_remaining / AGE_PENALTY_PER_DAY, 1)


def evaluate(spec: StabilitySpec) -> StabilityResult:
    score = stability_score(spec)
    status = stability_status(score)
    settling = stokes_settling_velocity(spec)
    risks: list[str] = []

    if abs(spec.zeta_mv) < ZETA_STABLE_MV:
        risks.append(
            f"zeta magnitude {abs(spec.zeta_mv):.1f} mV is below the "
            f"{ZETA_STABLE_MV:.1f} mV scenario threshold"
        )
    if spec.particle_size_nm > MAX_SAFE_PARTICLE_NM:
        risks.append(
            f"particle size {spec.particle_size_nm:.1f} nm exceeds the "
            f"{MAX_SAFE_PARTICLE_NM:.1f} nm scenario threshold"
        )
    if spec.volume_fraction > 0.05:
        risks.append(
            f"volume fraction {spec.volume_fraction * 100.0:.1f}% exceeds the "
            "5% scenario threshold"
        )
    if spec.age_days > 90:
        risks.append("age exceeds 90 scenario days; obtain a measurement before use")
    if settling > 50.0:
        risks.append(
            f"single-particle Stokes estimate {settling:.1f} nm/s exceeds "
            "the 50 nm/s review threshold"
        )

    return StabilityResult(
        spec=spec,
        stability_score=score,
        status=status,
        stokes_velocity_nm_s=round(settling, 6),
        estimated_remaining_days_to_monitor=estimated_remaining_days_to_monitor(
            spec
        ),
        risk_factors=tuple(risks),
        replacement_review_recommended=status in {"degrading", "unstable"},
    )


if __name__ == "__main__":
    sample = StabilitySpec(
        nanoparticle="Al2O3",
        base_fluid="water",
        volume_fraction=0.03,
        particle_size_nm=30.0,
        zeta_mv=38.0,
        age_days=27,
    )
    print(evaluate(sample))
