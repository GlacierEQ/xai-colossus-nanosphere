"""
xai-colossus-nanosphere: Nanofluid Thermal Performance Calculator
GlacierEQ Sovereign Stack | APEX Architecture

Models thermal conductivity enhancement for nanofluid coolants
used in xAI Colossus 2 cooling circuits.

Models implemented:
  - Maxwell (dilute suspension, spherical particles)
  - Hamilton-Crosser (non-spherical particles)
  - Degradation curve (exponential decay with age)
"""

from dataclasses import dataclass
from typing import Optional, List
import json
import math
import datetime


# Nanoparticle thermal conductivity (W/m·K) at 25°C
NANOPARTICLE_CONDUCTIVITY = {
    "Al2O3":    40.0,
    "TiO2":     11.8,
    "CuO":      76.5,
    "graphene": 5000.0,
    "SiC":      490.0,
    "ZnO":      29.0,
    "Fe3O4":    9.7,
}

# Nanoparticle shape factors for Hamilton-Crosser model
SHAPE_FACTOR = {
    "sphere":   3.0,
    "cylinder": 6.0,
    "blade":    8.0,
    "platelet": 5.7,
}

# Base fluid thermal conductivity (W/m·K) at 25°C
BASE_FLUID_CONDUCTIVITY = {
    "water":            0.613,
    "ethylene_glycol":  0.258,
    "water_eg_50_50":   0.405,
    "propylene_glycol": 0.215,
    "engine_oil":       0.145,
}

# Degradation half-life constants (days) per fluid type
DEGRADATION_HALFLIFE = {
    "Al2O3":    180,
    "TiO2":     150,
    "CuO":      90,
    "graphene": 120,
    "SiC":      200,
    "ZnO":      100,
    "Fe3O4":    75,
}


@dataclass
class NanofluidSpec:
    name: str
    base_fluid: str
    nanoparticle: str
    volume_fraction: float    # 0.0-0.10
    particle_size_nm: float
    particle_shape: str = "sphere"
    temperature_c: float = 25.0
    circuit_id: Optional[str] = None
    batch_date: Optional[str] = None


@dataclass
class FluidBatch:
    batch_id: str
    spec: NanofluidSpec
    install_date: str
    age_days: int = 0
    measured_conductivity: Optional[float] = None
    status: str = "active"  # active | degraded | replacement_due | retired

    def degradation_pct(self) -> float:
        halflife = DEGRADATION_HALFLIFE.get(self.spec.nanoparticle, 120)
        return (1 - math.exp(-0.693 * self.age_days / halflife)) * 100

    def effective_conductivity(self) -> float:
        base = maxwell_effective_conductivity(self.spec)
        deg = self.degradation_pct() / 100
        # At full degradation (100%), allow up to 40% drop in effective k
        return base * (1 - deg * 0.4)

    def needs_replacement(self) -> bool:
        return self.degradation_pct() > 15.0


def maxwell_effective_conductivity(spec: NanofluidSpec) -> float:
    """Maxwell model — spherical particles, dilute suspension."""
    k_f = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    k_p = NANOPARTICLE_CONDUCTIVITY[spec.nanoparticle]
    phi = spec.volume_fraction
    return k_f * (k_p + 2 * k_f + 2 * phi * (k_p - k_f)) / (
        k_p + 2 * k_f - phi * (k_p - k_f)
    )


def hamilton_crosser_conductivity(spec: NanofluidSpec) -> float:
    """Hamilton-Crosser model — accounts for particle shape."""
    k_f = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    k_p = NANOPARTICLE_CONDUCTIVITY[spec.nanoparticle]
    phi = spec.volume_fraction
    n = SHAPE_FACTOR.get(spec.particle_shape, 3.0)
    return k_f * (k_p + (n - 1) * k_f - (n - 1) * phi * (k_f - k_p)) / (
        k_p + (n - 1) * k_f + phi * (k_f - k_p)
    )


def enhancement_pct(spec: NanofluidSpec, model: str = "maxwell") -> float:
    k_base = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    if model == "maxwell":
        k_eff = maxwell_effective_conductivity(spec)
    else:
        k_eff = hamilton_crosser_conductivity(spec)
    return (k_eff - k_base) / k_base * 100


def recommend_blend(
    target_enhancement_pct: float,
    base_fluid: str = "water",
    max_volume_fraction: float = 0.05,
    particle_shape: str = "sphere",
) -> Optional[NanofluidSpec]:
    """
    Find the lowest-concentration blend that hits target enhancement.
    Searches high-k nanoparticles first, then increasing volume fraction.
    """
    candidates = []
    for particle in sorted(
        NANOPARTICLE_CONDUCTIVITY, key=lambda p: NANOPARTICLE_CONDUCTIVITY[p], reverse=True
    ):
        for phi in [0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10]:
            if phi > max_volume_fraction:
                continue
            spec = NanofluidSpec(
                name=f"{particle}_{int(phi*100)}pct_{particle_shape}",
                base_fluid=base_fluid,
                nanoparticle=particle,
                volume_fraction=phi,
                particle_size_nm=30.0,
                particle_shape=particle_shape,
            )
            enh = enhancement_pct(spec)
            if enh >= target_enhancement_pct:
                candidates.append((phi, enh, spec))
    if not candidates:
        return None
    candidates.sort(key=lambda x: x[0])  # lowest concentration wins
    return candidates[0][2]


def export_circuit_manifest(
    batches: List[FluidBatch],
    path: str = "integration/circuit_manifest.json",
) -> dict:
    """
    Export fluid state for all circuits — consumed by xai-colossus-cooling.
    """
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat(),
        "circuits": [
            {
                "batch_id": b.batch_id,
                "circuit_id": b.spec.circuit_id,
                "nanoparticle": b.spec.nanoparticle,
                "volume_fraction_pct": b.spec.volume_fraction * 100,
                "effective_conductivity_w_mk": round(b.effective_conductivity(), 4),
                "degradation_pct": round(b.degradation_pct(), 2),
                "status": b.status,
                "replacement_due": b.needs_replacement(),
            }
            for b in batches
        ],
    }
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    return manifest


if __name__ == "__main__":
    spec = NanofluidSpec(
        name="Colossus2-Primary",
        base_fluid="water",
        nanoparticle="Al2O3",
        volume_fraction=0.03,
        particle_size_nm=30.0,
        circuit_id="CIRCUIT-01",
    )
    print(f"Maxwell enhancement: {enhancement_pct(spec):.2f}%")
    print(f"HC enhancement:      {enhancement_pct(spec, model='hc'):.2f}%")

    batch = FluidBatch(
        batch_id="BATCH-001",
        spec=spec,
        install_date="2026-05-01",
        age_days=27,
    )
    print(f"Degradation at day 27: {batch.degradation_pct():.2f}%")
    print(f"Needs replacement: {batch.needs_replacement()}")

    print("\nOptimal blend for 20% target enhancement:")
    rec = recommend_blend(20.0, max_volume_fraction=0.05)
    if rec:
        print(f"  {rec.name} | {enhancement_pct(rec):.1f}% enhancement")
