from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from nanosphere_model import (
    FluidBatch,
    NanofluidInputError,
    NanofluidSpec,
    enhancement_pct,
    export_circuit_manifest,
    hamilton_crosser_conductivity,
    maxwell_effective_conductivity,
    recommend_blend,
)
from stability_model import (
    StabilitySpec,
    estimated_remaining_days_to_monitor,
    evaluate as evaluate_stability,
    stability_status,
    stokes_settling_velocity,
)
from viscosity_model import (
    ViscositySpec,
    base_viscosity_at_temperature_cp,
    evaluate as evaluate_viscosity,
    pump_penalty_pct,
    viscosity_sweep,
)


def fluid_spec(**overrides) -> NanofluidSpec:
    values = {
        "name": "sample",
        "base_fluid": "water",
        "nanoparticle": "Al2O3",
        "volume_fraction": 0.03,
        "particle_size_nm": 50.0,
    }
    values.update(overrides)
    return NanofluidSpec(**values)


def stability_spec(**overrides) -> StabilitySpec:
    values = {
        "nanoparticle": "Al2O3",
        "base_fluid": "water",
        "volume_fraction": 0.03,
        "particle_size_nm": 50.0,
        "zeta_mv": -35.0,
        "age_days": 30,
    }
    values.update(overrides)
    return StabilitySpec(**values)


def viscosity_spec(**overrides) -> ViscositySpec:
    values = {
        "base_fluid": "water",
        "volume_fraction": 0.03,
        "temperature_c": 30.0,
    }
    values.update(overrides)
    return ViscositySpec(**values)


# Conductivity and batch scenarios

def test_zero_fraction_matches_base_conductivity() -> None:
    spec = fluid_spec(volume_fraction=0.0)

    assert maxwell_effective_conductivity(spec) == pytest.approx(0.613)
    assert enhancement_pct(spec) == pytest.approx(0.0)


def test_maxwell_enhancement_is_positive_for_valid_suspension() -> None:
    assert enhancement_pct(fluid_spec()) > 0.0


def test_graphene_scenario_exceeds_alumina_at_same_fraction() -> None:
    graphene = enhancement_pct(fluid_spec(nanoparticle="graphene"))
    alumina = enhancement_pct(fluid_spec(nanoparticle="Al2O3"))

    assert graphene > alumina


def test_hamilton_crosser_accepts_explicit_model_name() -> None:
    spec = fluid_spec(particle_shape="platelet")

    assert hamilton_crosser_conductivity(spec) > 0.0
    assert enhancement_pct(spec, model="hamilton_crosser") > 0.0


def test_unknown_model_fails_closed() -> None:
    with pytest.raises(NanofluidInputError, match="conductivity model"):
        enhancement_pct(fluid_spec(), model="mystery")  # type: ignore[arg-type]


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"name": ""}, "name"),
        ({"base_fluid": "unknown"}, "base_fluid"),
        ({"nanoparticle": "unknown"}, "nanoparticle"),
        ({"particle_shape": "unknown"}, "particle_shape"),
        ({"volume_fraction": -0.01}, "volume_fraction"),
        ({"volume_fraction": 0.11}, "volume_fraction"),
        ({"particle_size_nm": 0.0}, "particle_size_nm"),
        ({"temperature_c": math.nan}, "temperature_c"),
    ],
)
def test_nanofluid_spec_rejects_invalid_inputs(overrides, message: str) -> None:
    with pytest.raises(NanofluidInputError, match=message):
        fluid_spec(**overrides)


def test_batch_degradation_increases_with_age() -> None:
    young = FluidBatch("young", fluid_spec(), "2026-01-01", age_days=1)
    old = FluidBatch("old", fluid_spec(), "2026-01-01", age_days=180)

    assert old.degradation_pct() > young.degradation_pct()
    assert old.effective_conductivity() < young.effective_conductivity()


def test_batch_replacement_threshold_is_configurable() -> None:
    batch = FluidBatch("batch", fluid_spec(), "2026-01-01", age_days=180)

    assert batch.needs_replacement(10.0) is True
    assert batch.needs_replacement(90.0) is False


@pytest.mark.parametrize(
    "kwargs,message",
    [
        ({"batch_id": ""}, "batch_id"),
        ({"age_days": -1}, "age_days"),
        ({"status": "mystery"}, "status"),
        ({"measured_conductivity": 0.0}, "measured_conductivity"),
    ],
)
def test_fluid_batch_rejects_invalid_inputs(kwargs, message: str) -> None:
    values = {
        "batch_id": "batch",
        "spec": fluid_spec(),
        "install_date": "2026-01-01",
    }
    values.update(kwargs)
    with pytest.raises(NanofluidInputError, match=message):
        FluidBatch(**values)


def test_blend_recommendation_is_deterministic() -> None:
    first = recommend_blend(5.0, max_volume_fraction=0.05)
    second = recommend_blend(5.0, max_volume_fraction=0.05)

    assert first == second
    assert first is not None
    assert first.volume_fraction <= 0.05
    assert enhancement_pct(first) >= 5.0


def test_blend_recommendation_returns_none_when_target_is_unreachable() -> None:
    assert recommend_blend(10_000.0, max_volume_fraction=0.005) is None


def test_manifest_export_is_atomic_sorted_and_explicit(tmp_path: Path) -> None:
    batches = [
        FluidBatch("b-2", fluid_spec(circuit_id="c-2"), "2026-01-01"),
        FluidBatch("b-1", fluid_spec(circuit_id="c-1"), "2026-01-01"),
    ]
    path = tmp_path / "nested" / "manifest.json"

    manifest = export_circuit_manifest(batches, path)
    stored = json.loads(path.read_text(encoding="utf-8"))

    assert stored == manifest
    assert manifest["schema"] == "glaciereq.nanofluid-circuit-manifest.v1"
    assert manifest["evidence_state"] == "MODELED_SCENARIO_NOT_TELEMETRY"
    assert [entry["batch_id"] for entry in manifest["circuits"]] == ["b-1", "b-2"]
    assert not path.with_suffix(".json.tmp").exists()


# Stability scenarios

def test_stability_score_stays_in_range() -> None:
    result = evaluate_stability(stability_spec())

    assert 0.0 <= result.stability_score <= 100.0
    assert result.status == "stable"


def test_lower_zeta_magnitude_reduces_stability() -> None:
    high = evaluate_stability(stability_spec(zeta_mv=-45.0))
    low = evaluate_stability(stability_spec(zeta_mv=-10.0))

    assert high.stability_score > low.stability_score


def test_larger_particles_increase_settling_estimate() -> None:
    small = stokes_settling_velocity(stability_spec(particle_size_nm=20.0))
    large = stokes_settling_velocity(stability_spec(particle_size_nm=100.0))

    assert large > small >= 0.0


def test_age_alone_may_never_cross_monitor_threshold() -> None:
    remaining = estimated_remaining_days_to_monitor(
        stability_spec(zeta_mv=-45.0, age_days=0)
    )

    assert math.isinf(remaining)


def test_remaining_days_counts_from_current_age() -> None:
    fresh = estimated_remaining_days_to_monitor(
        stability_spec(zeta_mv=-20.0, age_days=0)
    )
    older = estimated_remaining_days_to_monitor(
        stability_spec(zeta_mv=-20.0, age_days=20)
    )

    assert older < fresh


def test_degrading_state_recommends_review() -> None:
    result = evaluate_stability(
        stability_spec(
            zeta_mv=-10.0,
            particle_size_nm=120.0,
            volume_fraction=0.08,
            age_days=120,
        )
    )

    assert result.status in {"degrading", "unstable"}
    assert result.replacement_review_recommended is True
    assert result.risk_factors


@pytest.mark.parametrize(
    "score,status",
    [(100.0, "stable"), (80.0, "stable"), (79.9, "monitor"), (60.0, "monitor"), (59.9, "degrading"), (40.0, "degrading"), (39.9, "unstable")],
)
def test_stability_status_boundaries(score: float, status: str) -> None:
    assert stability_status(score) == status


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"nanoparticle": "unknown"}, "nanoparticle"),
        ({"base_fluid": "unknown"}, "base_fluid"),
        ({"volume_fraction": 0.11}, "volume_fraction"),
        ({"particle_size_nm": 0.0}, "particle_size_nm"),
        ({"zeta_mv": math.inf}, "zeta_mv"),
        ({"age_days": -1}, "age_days"),
    ],
)
def test_stability_spec_rejects_invalid_inputs(overrides, message: str) -> None:
    with pytest.raises(NanofluidInputError, match=message):
        stability_spec(**overrides)


# Viscosity and comparative pump scenarios

def test_zero_fraction_has_zero_modeled_pump_penalty() -> None:
    assert pump_penalty_pct(viscosity_spec(volume_fraction=0.0)) == pytest.approx(0.0)


def test_higher_fraction_increases_modeled_penalty() -> None:
    low = pump_penalty_pct(viscosity_spec(volume_fraction=0.01))
    high = pump_penalty_pct(viscosity_spec(volume_fraction=0.08))

    assert high > low > 0.0


def test_non_spherical_factor_increases_modeled_penalty() -> None:
    sphere = pump_penalty_pct(viscosity_spec(particle_shape_factor=1.0))
    platelet = pump_penalty_pct(viscosity_spec(particle_shape_factor=2.0))

    assert platelet > sphere


def test_temperature_changes_base_viscosity_not_same_temperature_ratio() -> None:
    cold = viscosity_spec(temperature_c=25.0)
    warm = viscosity_spec(temperature_c=40.0)

    assert base_viscosity_at_temperature_cp(warm) < base_viscosity_at_temperature_cp(cold)
    assert pump_penalty_pct(warm) == pytest.approx(pump_penalty_pct(cold))


def test_viscosity_result_exposes_same_temperature_baseline() -> None:
    result = evaluate_viscosity(viscosity_spec())

    assert result.base_viscosity_at_temperature_cp > 0.0
    assert result.effective_viscosity_cp > result.base_viscosity_at_temperature_cp
    assert result.viscosity_ratio > 1.0
    assert result.pump_penalty_pct > 0.0


def test_viscosity_sweep_is_ordered_and_complete() -> None:
    sweep = viscosity_sweep("water", temperature_c=30.0)

    assert len(sweep) == 10
    assert [row["volume_fraction_pct"] for row in sweep] == sorted(
        row["volume_fraction_pct"] for row in sweep
    )
    assert sweep[-1]["modeled_pump_penalty_pct"] > sweep[0]["modeled_pump_penalty_pct"]


@pytest.mark.parametrize(
    "overrides,message",
    [
        ({"base_fluid": "unknown"}, "base_fluid"),
        ({"volume_fraction": -0.01}, "volume_fraction"),
        ({"volume_fraction": 0.11}, "volume_fraction"),
        ({"temperature_c": math.nan}, "temperature_c"),
        ({"particle_shape_factor": 0.0}, "particle_shape_factor"),
    ],
)
def test_viscosity_spec_rejects_invalid_inputs(overrides, message: str) -> None:
    with pytest.raises(NanofluidInputError, match=message):
        viscosity_spec(**overrides)
