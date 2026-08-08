"""Bounded nanofluid conductivity and batch-degradation scenario models.

The equations and constants in this module are portfolio assumptions for
comparative simulation. They are not material certifications, laboratory
measurements, or authorization to use a blend in physical infrastructure.
"""

from __future__ import annotations

import json
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal


class NanofluidInputError(ValueError):
    """Raised when a nanofluid scenario contains invalid inputs."""


NANOPARTICLE_CONDUCTIVITY = {
    "Al2O3": 40.0,
    "TiO2": 11.8,
    "CuO": 76.5,
    "graphene": 5000.0,
    "SiC": 490.0,
    "ZnO": 29.0,
    "Fe3O4": 9.7,
}

SHAPE_FACTOR = {
    "sphere": 3.0,
    "cylinder": 6.0,
    "blade": 8.0,
    "platelet": 5.7,
}

BASE_FLUID_CONDUCTIVITY = {
    "water": 0.613,
    "ethylene_glycol": 0.258,
    "water_eg_50_50": 0.405,
    "propylene_glycol": 0.215,
    "engine_oil": 0.145,
}

DEGRADATION_HALFLIFE_DAYS = {
    "Al2O3": 180.0,
    "TiO2": 150.0,
    "CuO": 90.0,
    "graphene": 120.0,
    "SiC": 200.0,
    "ZnO": 100.0,
    "Fe3O4": 75.0,
}

ALLOWED_BATCH_STATUSES = {"active", "degraded", "replacement_due", "retired"}
ConductivityModel = Literal["maxwell", "hamilton_crosser"]


def _require_finite(name: str, value: float) -> float:
    if not isinstance(value, (int, float)) or isinstance(value, bool):
        raise NanofluidInputError(f"{name} must be numeric")
    numeric = float(value)
    if not math.isfinite(numeric):
        raise NanofluidInputError(f"{name} must be finite")
    return numeric


def _require_optional_identifier(name: str, value: str | None) -> None:
    if value is not None and (not isinstance(value, str) or not value.strip()):
        raise NanofluidInputError(f"{name} must be a non-empty string when provided")


@dataclass(frozen=True, slots=True)
class NanofluidSpec:
    name: str
    base_fluid: str
    nanoparticle: str
    volume_fraction: float
    particle_size_nm: float
    particle_shape: str = "sphere"
    temperature_c: float = 25.0
    circuit_id: str | None = None
    batch_date: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise NanofluidInputError("name must be a non-empty string")
        if self.base_fluid not in BASE_FLUID_CONDUCTIVITY:
            raise NanofluidInputError(f"unsupported base_fluid: {self.base_fluid}")
        if self.nanoparticle not in NANOPARTICLE_CONDUCTIVITY:
            raise NanofluidInputError(f"unsupported nanoparticle: {self.nanoparticle}")
        if self.particle_shape not in SHAPE_FACTOR:
            raise NanofluidInputError(f"unsupported particle_shape: {self.particle_shape}")

        phi = _require_finite("volume_fraction", self.volume_fraction)
        if not 0.0 <= phi <= 0.10:
            raise NanofluidInputError("volume_fraction must be between 0.0 and 0.10")
        particle_size = _require_finite("particle_size_nm", self.particle_size_nm)
        if particle_size <= 0.0:
            raise NanofluidInputError("particle_size_nm must be greater than zero")
        _require_finite("temperature_c", self.temperature_c)
        _require_optional_identifier("circuit_id", self.circuit_id)
        _require_optional_identifier("batch_date", self.batch_date)


@dataclass(slots=True)
class FluidBatch:
    batch_id: str
    spec: NanofluidSpec
    install_date: str
    age_days: int = 0
    measured_conductivity: float | None = None
    status: str = "active"

    def __post_init__(self) -> None:
        if not isinstance(self.batch_id, str) or not self.batch_id.strip():
            raise NanofluidInputError("batch_id must be a non-empty string")
        if not isinstance(self.spec, NanofluidSpec):
            raise NanofluidInputError("spec must be a NanofluidSpec")
        if not isinstance(self.install_date, str) or not self.install_date.strip():
            raise NanofluidInputError("install_date must be a non-empty string")
        if not isinstance(self.age_days, int) or isinstance(self.age_days, bool):
            raise NanofluidInputError("age_days must be an integer")
        if self.age_days < 0:
            raise NanofluidInputError("age_days cannot be negative")
        if self.measured_conductivity is not None:
            measured = _require_finite(
                "measured_conductivity", self.measured_conductivity
            )
            if measured <= 0.0:
                raise NanofluidInputError(
                    "measured_conductivity must be greater than zero"
                )
        if self.status not in ALLOWED_BATCH_STATUSES:
            raise NanofluidInputError(f"unsupported batch status: {self.status}")

    def degradation_fraction(self) -> float:
        """Scenario degradation fraction using a configured exponential half-life."""

        half_life = DEGRADATION_HALFLIFE_DAYS[self.spec.nanoparticle]
        return 1.0 - math.exp(-math.log(2.0) * self.age_days / half_life)

    def degradation_pct(self) -> float:
        return self.degradation_fraction() * 100.0

    def effective_conductivity(self) -> float:
        modeled = maxwell_effective_conductivity(self.spec)
        # Portfolio assumption: full modeled degradation can reduce the
        # conductivity estimate by at most 40 percent.
        return modeled * (1.0 - self.degradation_fraction() * 0.40)

    def needs_replacement(self, threshold_pct: float = 15.0) -> bool:
        threshold = _require_finite("threshold_pct", threshold_pct)
        if not 0.0 <= threshold <= 100.0:
            raise NanofluidInputError("threshold_pct must be between 0 and 100")
        return self.degradation_pct() > threshold


def maxwell_effective_conductivity(spec: NanofluidSpec) -> float:
    """Maxwell dilute-suspension scenario for spherical particles."""

    k_f = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    k_p = NANOPARTICLE_CONDUCTIVITY[spec.nanoparticle]
    phi = float(spec.volume_fraction)
    denominator = k_p + 2.0 * k_f - phi * (k_p - k_f)
    if denominator <= 0.0:
        raise NanofluidInputError("Maxwell model denominator must remain positive")
    return k_f * (k_p + 2.0 * k_f + 2.0 * phi * (k_p - k_f)) / denominator


def hamilton_crosser_conductivity(spec: NanofluidSpec) -> float:
    """Hamilton-Crosser comparative scenario using a declared shape factor."""

    k_f = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    k_p = NANOPARTICLE_CONDUCTIVITY[spec.nanoparticle]
    phi = float(spec.volume_fraction)
    n = SHAPE_FACTOR[spec.particle_shape]
    denominator = k_p + (n - 1.0) * k_f + phi * (k_f - k_p)
    if denominator <= 0.0:
        raise NanofluidInputError(
            "Hamilton-Crosser model denominator must remain positive"
        )
    return k_f * (
        k_p + (n - 1.0) * k_f - (n - 1.0) * phi * (k_f - k_p)
    ) / denominator


def enhancement_pct(
    spec: NanofluidSpec,
    model: ConductivityModel = "maxwell",
) -> float:
    if model == "maxwell":
        effective = maxwell_effective_conductivity(spec)
    elif model == "hamilton_crosser":
        effective = hamilton_crosser_conductivity(spec)
    else:
        raise NanofluidInputError(f"unsupported conductivity model: {model}")
    base = BASE_FLUID_CONDUCTIVITY[spec.base_fluid]
    return (effective - base) / base * 100.0


def recommend_blend(
    target_enhancement_pct: float,
    base_fluid: str = "water",
    max_volume_fraction: float = 0.05,
    particle_shape: str = "sphere",
    model: ConductivityModel = "maxwell",
) -> NanofluidSpec | None:
    """Return the lowest modeled concentration meeting a target scenario.

    Ties are resolved deterministically by higher modeled enhancement and then
    particle name. This is a comparative search, not a formulation recommendation.
    """

    target = _require_finite("target_enhancement_pct", target_enhancement_pct)
    if target < 0.0:
        raise NanofluidInputError("target_enhancement_pct cannot be negative")
    if base_fluid not in BASE_FLUID_CONDUCTIVITY:
        raise NanofluidInputError(f"unsupported base_fluid: {base_fluid}")
    maximum = _require_finite("max_volume_fraction", max_volume_fraction)
    if not 0.0 <= maximum <= 0.10:
        raise NanofluidInputError(
            "max_volume_fraction must be between 0.0 and 0.10"
        )
    if particle_shape not in SHAPE_FACTOR:
        raise NanofluidInputError(f"unsupported particle_shape: {particle_shape}")
    if model not in ("maxwell", "hamilton_crosser"):
        raise NanofluidInputError(f"unsupported conductivity model: {model}")

    fractions = (0.005, 0.01, 0.02, 0.03, 0.04, 0.05, 0.07, 0.10)
    candidates: list[tuple[float, float, str, NanofluidSpec]] = []
    for particle in sorted(NANOPARTICLE_CONDUCTIVITY):
        for phi in fractions:
            if phi > maximum:
                continue
            spec = NanofluidSpec(
                name=f"{particle}_{phi:.3f}_{particle_shape}",
                base_fluid=base_fluid,
                nanoparticle=particle,
                volume_fraction=phi,
                particle_size_nm=30.0,
                particle_shape=particle_shape,
            )
            modeled = enhancement_pct(spec, model=model)
            if modeled >= target:
                candidates.append((phi, -modeled, particle, spec))

    if not candidates:
        return None
    candidates.sort(key=lambda item: (item[0], item[1], item[2]))
    return candidates[0][3]


def export_circuit_manifest(
    batches: list[FluidBatch],
    path: str | os.PathLike[str] = "integration/circuit_manifest.json",
) -> dict:
    """Write a deterministic, atomic scenario manifest for another model.

    The manifest records modeled values and assumptions. It is not telemetry and
    does not prove a live connection to a cooling controller.
    """

    if not isinstance(batches, list) or not all(
        isinstance(batch, FluidBatch) for batch in batches
    ):
        raise NanofluidInputError("batches must be a list of FluidBatch values")

    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    manifest = {
        "schema": "glaciereq.nanofluid-circuit-manifest.v1",
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "evidence_state": "MODELED_SCENARIO_NOT_TELEMETRY",
        "assumptions": {
            "conductivity_model": "maxwell",
            "degradation_curve": "exponential_half_life",
            "maximum_modeled_conductivity_drop_fraction": 0.40,
            "replacement_threshold_pct": 15.0,
        },
        "circuits": [
            {
                "batch_id": batch.batch_id,
                "circuit_id": batch.spec.circuit_id,
                "nanoparticle": batch.spec.nanoparticle,
                "base_fluid": batch.spec.base_fluid,
                "volume_fraction_pct": round(batch.spec.volume_fraction * 100.0, 6),
                "particle_size_nm": float(batch.spec.particle_size_nm),
                "modeled_effective_conductivity_w_mk": round(
                    batch.effective_conductivity(), 6
                ),
                "modeled_degradation_pct": round(batch.degradation_pct(), 6),
                "status": batch.status,
                "replacement_due": batch.needs_replacement(),
                "measured_conductivity_w_mk": batch.measured_conductivity,
            }
            for batch in sorted(batches, key=lambda item: item.batch_id)
        ],
    }

    temporary = destination.with_suffix(destination.suffix + ".tmp")
    temporary.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    os.replace(temporary, destination)
    return manifest


if __name__ == "__main__":
    sample = NanofluidSpec(
        name="portfolio-scenario",
        base_fluid="water",
        nanoparticle="Al2O3",
        volume_fraction=0.03,
        particle_size_nm=30.0,
        circuit_id="CIRCUIT-01",
    )
    print(f"Maxwell enhancement: {enhancement_pct(sample):.2f}%")
    print(
        "Hamilton-Crosser enhancement: "
        f"{enhancement_pct(sample, model='hamilton_crosser'):.2f}%"
    )
