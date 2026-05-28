"""
viscosity_model.py — Nanofluid Viscosity and Pump Penalty Engine
GlacierEQ Sovereign Stack | APEX Architecture

Models effective viscosity of nanofluid suspensions using the
Einstein + Batchelor model for dilute suspensions (phi < 0.10)
with an empirical temperature correction factor.

Key output: pump_penalty_pct — the % increase in pumping power
required versus the pure base fluid at the same flow conditions.
This is the primary cost side of the thermal enhancement tradeoff.

References:
  - Einstein (1906): mu_eff = mu0 * (1 + 2.5*phi)
  - Batchelor (1977): adds phi^2 term for hydrodynamic interactions
  - Krieger-Dougherty model (concentrated, phi > 0.10) — see MODELS.md
"""

from dataclasses import dataclass, field
from typing import Optional
import math


# Base fluid dynamic viscosity at 25°C (cP = mPa·s)
BASE_VISCOSITY_CP = {
    "water":            0.89,
    "ethylene_glycol":  16.1,
    "water_eg_50_50":   3.4,
    "propylene_glycol": 52.0,
    "engine_oil":       86.0,
}

# Viscosity-temperature sensitivity coefficient (empirical, per °C above 25°C)
# Represents fractional viscosity reduction per degree
TEMP_SENSITIVITY = {
    "water":            0.020,
    "ethylene_glycol":  0.035,
    "water_eg_50_50":   0.027,
    "propylene_glycol": 0.045,
    "engine_oil":       0.060,
}

# Maximum viscosity ratio caps per fluid class (safety ceiling for dense slurries)
MAX_VISCOSITY_RATIO = {
    "water":            3.5,
    "ethylene_glycol":  3.0,
    "water_eg_50_50":   3.2,
    "propylene_glycol": 2.8,
    "engine_oil":       2.5,
}

# Pump power scales with viscosity^0.75 for turbulent flow (Dittus-Boelter regime)
# For laminar flow it scales linearly; 0.75 is the Colossus 2 turbulent-regime assumption
PUMP_VISCOSITY_EXPONENT = 0.75


@dataclass
class ViscositySpec:
    base_fluid: str
    volume_fraction: float          # 0.0 – 0.10
    temperature_c: float = 25.0
    particle_shape_factor: float = 1.0   # 1.0 = sphere; >1 for rods/platelets
    circuit_id: Optional[str] = None


@dataclass
class ViscosityResult:
    spec: ViscositySpec
    base_viscosity_cp: float
    effective_viscosity_cp: float
    viscosity_ratio: float
    pump_penalty_pct: float
    regime: str                     # "acceptable" | "elevated" | "excessive"
    warning: Optional[str] = None


def effective_viscosity_cp(spec: ViscositySpec) -> float:
    """
    Einstein-Batchelor model with temperature correction.

    mu_eff = mu0 * (1 + 2.5*phi + 6.2*phi^2) * shape_factor * temp_factor

    shape_factor scales the phi terms for non-spherical particles:
      - sphere: 1.0 (shape_factor = 1.0, no adjustment)
      - cylinder: 1.5 (approximate; use spec.particle_shape_factor)
      - platelet: 2.0 (approximate)

    temp_factor decreases viscosity above 25°C baseline.
    """
    mu0 = BASE_VISCOSITY_CP[spec.base_fluid]
    phi = spec.volume_fraction
    sensitivity = TEMP_SENSITIVITY.get(spec.base_fluid, 0.025)
    delta_t = spec.temperature_c - 25.0
    temp_factor = max(0.35, 1.0 - sensitivity * delta_t)

    einstein_batchelor = 1.0 + 2.5 * phi * spec.particle_shape_factor + \
                         6.2 * (phi * spec.particle_shape_factor) ** 2

    mu_eff = mu0 * einstein_batchelor * temp_factor

    # Cap at physical maximum for safety
    max_ratio = MAX_VISCOSITY_RATIO.get(spec.base_fluid, 3.0)
    return min(mu_eff, mu0 * max_ratio)


def pump_penalty_pct(spec: ViscositySpec) -> float:
    """
    Pump power penalty vs pure base fluid.

    In turbulent flow (Re > 4000, typical for Colossus 2 primary circuits):
      P_pump ∝ mu^0.75

    So penalty = ((mu_eff / mu0)^0.75 - 1) * 100
    """
    mu0 = BASE_VISCOSITY_CP[spec.base_fluid]
    mu_eff = effective_viscosity_cp(spec)
    ratio = mu_eff / mu0
    return (ratio ** PUMP_VISCOSITY_EXPONENT - 1.0) * 100.0


def evaluate(spec: ViscositySpec) -> ViscosityResult:
    """Full viscosity evaluation with regime classification."""
    mu0 = BASE_VISCOSITY_CP[spec.base_fluid]
    mu_eff = effective_viscosity_cp(spec)
    ratio = mu_eff / mu0
    penalty = pump_penalty_pct(spec)

    if penalty < 10.0:
        regime = "acceptable"
        warning = None
    elif penalty < 25.0:
        regime = "elevated"
        warning = f"Pump penalty {penalty:.1f}% — verify flow rate margins"
    else:
        regime = "excessive"
        warning = f"Pump penalty {penalty:.1f}% exceeds 25% threshold — reduce phi or switch base fluid"

    return ViscosityResult(
        spec=spec,
        base_viscosity_cp=mu0,
        effective_viscosity_cp=round(mu_eff, 4),
        viscosity_ratio=round(ratio, 4),
        pump_penalty_pct=round(penalty, 2),
        regime=regime,
        warning=warning,
    )


def viscosity_sweep(base_fluid: str, temperature_c: float = 25.0) -> list:
    """
    Sweep volume fractions 0.5% to 10% and return penalty curve.
    Used for blend selection and circuit engineering.
    """
    results = []
    for phi_pct in [0.5, 1.0, 1.5, 2.0, 2.5, 3.0, 4.0, 5.0, 7.0, 10.0]:
        spec = ViscositySpec(
            base_fluid=base_fluid,
            volume_fraction=phi_pct / 100.0,
            temperature_c=temperature_c,
        )
        r = evaluate(spec)
        results.append({
            "volume_fraction_pct": phi_pct,
            "effective_viscosity_cp": r.effective_viscosity_cp,
            "pump_penalty_pct": r.pump_penalty_pct,
            "regime": r.regime,
        })
    return results


if __name__ == "__main__":
    print("=== Viscosity Sweep: Al2O3/water at 40°C ===")
    for row in viscosity_sweep("water", temperature_c=40.0):
        print(f"  phi={row['volume_fraction_pct']}%  "
              f"mu={row['effective_viscosity_cp']:.3f} cP  "
              f"pump+{row['pump_penalty_pct']:.1f}%  [{row['regime']}]")

    print("\n=== Single Point Evaluation ===")
    spec = ViscositySpec(base_fluid="water", volume_fraction=0.03, temperature_c=40.0)
    result = evaluate(spec)
    print(f"  Base: {result.base_viscosity_cp} cP")
    print(f"  Effective: {result.effective_viscosity_cp} cP")
    print(f"  Pump penalty: {result.pump_penalty_pct}%")
    print(f"  Regime: {result.regime}")
    if result.warning:
        print(f"  WARNING: {result.warning}")
