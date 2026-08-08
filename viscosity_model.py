"""Bounded viscosity and pump-penalty scenarios for dilute nanofluids.

The implementation is comparative only. Coefficients are explicit assumptions
and do not replace measured rheology, pump curves, or engineering review.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

from nanosphere_model import NanofluidInputError


BASE_VISCOSITY_CP = {
    "water": 0.89,
    "ethylene_glycol": 16.1,
    "water_eg_50_50": 3.4,
    "propylene_glycol": 52.0,
    "engine_oil": 86.0,
}

TEMP_SENSITIVITY = {
    "water": 0.020,
    "ethylene_glycol": 0.035,
    "water_eg_50_50": 0.027,
    "propylene_glycol": 0.045,
    "engine_oil": 0.060,
}

MAX_VISCOSITY_RATIO = {
    "water": 3.5,
    "ethylene_glycol": 3.0,
    "water_eg_50_50": 3.2,
    "propylene_glycol": 2.8,
    "engine_oil": 2.5,
}

PUMP_VISCOSITY_EXPONENT = 0.75


def _finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise NanofluidInputError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise NanofluidInputError(f"{name} must be finite")
    return numeric


@dataclass(frozen=True, slots=True)
class ViscositySpec:
    base_fluid: str
    volume_fraction: float
    temperature_c: float = 25.0
    particle_shape_factor: float = 1.0
    circuit_id: str | None = None

    def __post_init__(self) -> None:
        if self.base_fluid not in BASE_VISCOSITY_CP:
            raise NanofluidInputError(f"unsupported base_fluid: {self.base_fluid}")
        phi = _finite("volume_fraction", self.volume_fraction)
        if not 0.0 <= phi <= 0.10:
            raise NanofluidInputError("volume_fraction must be between 0.0 and 0.10")
        _finite("temperature_c", self.temperature_c)
        shape = _finite("particle_shape_factor", self.particle_shape_factor)
        if shape <= 0.0:
            raise NanofluidInputError("particle_shape_factor must be greater than zero")
        if self.circuit_id is not None and (
            not isinstance(self.circuit_id, str) or not self.circuit_id.strip()
        ):
            raise NanofluidInputError(
                "circuit_id must be a non-empty string when provided"
            )


@dataclass(frozen=True, slots=True)
class ViscosityResult:
    spec: ViscositySpec
    base_viscosity_at_temperature_cp: float
    effective_viscosity_cp: float
    viscosity_ratio: float
    pump_penalty_pct: float
    regime: str
    warning: str | None = None


def base_viscosity_at_temperature_cp(spec: ViscositySpec) -> float:
    base_25 = BASE_VISCOSITY_CP[spec.base_fluid]
    sensitivity = TEMP_SENSITIVITY[spec.base_fluid]
    factor = max(0.35, 1.0 - sensitivity * (spec.temperature_c - 25.0))
    return base_25 * factor


def suspension_viscosity_ratio(spec: ViscositySpec) -> float:
    effective_phi = spec.volume_fraction * spec.particle_shape_factor
    raw_ratio = 1.0 + 2.5 * effective_phi + 6.2 * effective_phi**2
    return min(raw_ratio, MAX_VISCOSITY_RATIO[spec.base_fluid])


def effective_viscosity_cp(spec: ViscositySpec) -> float:
    return base_viscosity_at_temperature_cp(spec) * suspension_viscosity_ratio(spec)


def pump_penalty_pct(spec: ViscositySpec) -> float:
    """Comparative pump-power penalty at the same modeled temperature."""

    ratio = suspension_viscosity_ratio(spec)
    return (ratio**PUMP_VISCOSITY_EXPONENT - 1.0) * 100.0


def evaluate(spec: ViscositySpec) -> ViscosityResult:
    base = base_viscosity_at_temperature_cp(spec)
    ratio = suspension_viscosity_ratio(spec)
    effective = base * ratio
    penalty = pump_penalty_pct(spec)

    if penalty < 10.0:
        regime = "acceptable"
        warning = None
    elif penalty < 25.0:
        regime = "elevated"
        warning = (
            f"modeled pump penalty {penalty:.1f}% exceeds the 10% review threshold"
        )
    else:
        regime = "excessive"
        warning = (
            f"modeled pump penalty {penalty:.1f}% exceeds the 25% review threshold"
        )

    return ViscosityResult(
        spec=spec,
        base_viscosity_at_temperature_cp=round(base, 6),
        effective_viscosity_cp=round(effective, 6),
        viscosity_ratio=round(ratio, 6),
        pump_penalty_pct=round(penalty, 6),
        regime=regime,
        warning=warning,
    )


def viscosity_sweep(base_fluid: str, temperature_c: float = 25.0) -> list[dict]:
    if base_fluid not in BASE_VISCOSITY_CP:
        raise NanofluidInputError(f"unsupported base_fluid: {base_fluid}")
    _finite("temperature_c", temperature_c)

    results: list[dict] = []
    for phi_pct in (0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0):
        result = evaluate(
            ViscositySpec(
                base_fluid=base_fluid,
                volume_fraction=phi_pct / 100.0,
                temperature_c=temperature_c,
            )
        )
        results.append(
            {
                "volume_fraction_pct": phi_pct,
                "base_viscosity_at_temperature_cp": result.base_viscosity_at_temperature_cp,
                "effective_viscosity_cp": result.effective_viscosity_cp,
                "viscosity_ratio": result.viscosity_ratio,
                "modeled_pump_penalty_pct": result.pump_penalty_pct,
                "regime": result.regime,
            }
        )
    return results


if __name__ == "__main__":
    for row in viscosity_sweep("water", temperature_c=40.0):
        print(row)
