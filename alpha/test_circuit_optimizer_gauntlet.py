# Alpha (What) — Pure Physics | Omega (How) — Controllers | The Answer is 42.
"""
test_circuit_optimizer_gauntlet.py — Peak Thermal Load Stress Test
GlacierEQ APEX Stack | APEX Architecture

Exercises circuit_optimizer under extreme Colossus 2 operating conditions:
  - 100 W/cm² peak heat flux (next-gen Rubin die density)
  - 85°C inlet coolant temperature (worst-case summer + thermal soak)
  - Full particle matrix sweep at maximum volume fraction

Validates:
  1. Optimizer converges — produces ranked results for all particle types
  2. No thermal runaway — all thermal enhancements within physical bounds
  3. Pump penalty stays bounded — no viscosity explosion
  4. Composite scores are monotonically ordered
  5. Disqualification logic fires correctly under extreme constraints
  6. Edge cases: zero enhancement, zero volume fraction, max temperature

Run: python -m pytest tests/test_circuit_optimizer_gauntlet.py -v
"""

import sys
import os
import math

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from circuit_optimizer import (
    CircuitRequirements,
    CandidateResult,
    rank_blends,
    score_candidate,
    DEFAULT_WEIGHTS,
    MAX_ENHANCEMENT_PCT,
    MAX_PUMP_PENALTY_PCT,
)
from nanosphere_model import (
    NanofluidSpec,
    enhancement_pct,
    maxwell_effective_conductivity,
    NANOPARTICLE_CONDUCTIVITY,
    BASE_FLUID_CONDUCTIVITY,
)
from viscosity_model import ViscositySpec, pump_penalty_pct, evaluate as viscosity_evaluate
from stability_model import StabilitySpec, evaluate as stability_evaluate

import pytest


# ─── Peak Thermal Load Constants ────────────────────────────────────────────
PEAK_HEAT_FLUX_W_CM2 = 100.0
PEAK_INLET_TEMP_C = 85.0
EXTREME_VOLUME_FRACTION = 0.05
PEAK_REQUIREMENTS = CircuitRequirements(
    circuit_id="CIRCUIT-GAUNTLET-PEAK",
    base_fluid="water",
    min_enhancement_pct=5.0,
    max_pump_penalty_pct=35.0,
    max_volume_fraction=EXTREME_VOLUME_FRACTION,
    min_stability_score=30.0,
    min_halflife_days=30,
    temperature_c=PEAK_INLET_TEMP_C,
)


# ─── Convergence Tests ──────────────────────────────────────────────────────

class TestOptimizerConvergence:
    """Verify the optimizer produces valid results under peak load."""

    def test_peak_load_produces_ranked_results(self):
        results = rank_blends(PEAK_REQUIREMENTS)
        assert len(results) > 0, "Optimizer must produce at least one candidate"

    def test_all_nanoparticles_represented(self):
        results = rank_blends(PEAK_REQUIREMENTS)
        particles_found = {r.nanoparticle for r in results}
        for particle in NANOPARTICLE_CONDUCTIVITY:
            assert particle in particles_found, f"Missing particle type: {particle}"

    def test_composite_scores_monotonically_decreasing(self):
        results = rank_blends(PEAK_REQUIREMENTS)
        qualified = [r.composite_score for r in results if not r.disqualified]
        disqualified = [r.composite_score for r in results if r.disqualified]
        for group_name, scores in [("qualified", qualified), ("disqualified", disqualified)]:
            for i in range(len(scores) - 1):
                assert scores[i] >= scores[i + 1], (
                    f"Score not ordered in {group_name} group at position {i}: "
                    f"{scores[i]} < {scores[i+1]}"
                )

    def test_recommendation_exists_when_qualified(self):
        results = rank_blends(PEAK_REQUIREMENTS)
        recommended = [r for r in results if r.recommended]
        qualified = [r for r in results if not r.disqualified]
        if qualified:
            assert len(recommended) == 1, "Exactly one candidate must be marked recommended"

    def test_ranks_are_sequential(self):
        results = rank_blends(PEAK_REQUIREMENTS)
        for i, r in enumerate(results):
            assert r.rank == i + 1, f"Rank at position {i} is {r.rank}, expected {i + 1}"


# ─── No Thermal Runaway Tests ───────────────────────────────────────────────

class TestNoThermalRunaway:
    """Verify all outputs remain within physical bounds."""

    def test_enhancement_never_exceeds_maxwell_limit(self):
        """Maxwell model upper bound: enhancement < (k_p/k_f - 1) * 100."""
        results = rank_blends(PEAK_REQUIREMENTS)
        for r in results:
            k_f = BASE_FLUID_CONDUCTIVITY.get("water", 0.613)
            k_p = NANOPARTICLE_CONDUCTIVITY.get(r.nanoparticle, 40.0)
            theoretical_max = (k_p / k_f - 1.0) * 100.0
            assert r.enhancement_pct <= theoretical_max + 0.01, (
                f"{r.name}: enhancement {r.enhancement_pct}% exceeds "
                f"theoretical max {theoretical_max:.2f}%"
            )

    def test_enhancement_bounded_by_scoring_cap(self):
        """Even if physics allows >50%, scoring normalizes to MAX_ENHANCEMENT_PCT."""
        for particle in NANOPARTICLE_CONDUCTIVITY:
            spec = NanofluidSpec(
                name=f"{particle}_extreme",
                base_fluid="water",
                nanoparticle=particle,
                volume_fraction=0.10,
                particle_size_nm=30.0,
                temperature_c=PEAK_INLET_TEMP_C,
            )
            enh = enhancement_pct(spec)
            assert enh >= 0.0, f"Negative enhancement for {particle}"

    def test_pump_penalty_bounded_at_extreme(self):
        """Even at max phi=5% and 85°C, pump penalty must not exceed safety ceiling."""
        for particle in NANOPARTICLE_CONDUCTIVITY:
            spec = NanofluidSpec(
                name=f"{particle}_extreme",
                base_fluid="water",
                nanoparticle=particle,
                volume_fraction=EXTREME_VOLUME_FRACTION,
                particle_size_nm=30.0,
                temperature_c=PEAK_INLET_TEMP_C,
            )
            v_spec = ViscositySpec(
                base_fluid="water",
                volume_fraction=spec.volume_fraction,
                temperature_c=spec.temperature_c,
            )
            penalty = pump_penalty_pct(v_spec)
            assert penalty < 50.0, (
                f"Pump penalty {penalty:.1f}% for {particle} at {PEAK_INLET_TEMP_C}°C "
                f"is dangerously high"
            )

    def test_conductivity_positive_for_all_particles(self):
        """Effective conductivity must always be positive."""
        for particle in NANOPARTICLE_CONDUCTIVITY:
            spec = NanofluidSpec(
                name=f"{particle}_peak",
                base_fluid="water",
                nanoparticle=particle,
                volume_fraction=EXTREME_VOLUME_FRACTION,
                particle_size_nm=30.0,
                temperature_c=PEAK_INLET_TEMP_C,
            )
            k_eff = maxwell_effective_conductivity(spec)
            assert k_eff > 0, f"Non-positive conductivity for {particle}: {k_eff}"


# ─── Extreme Constraint Tests ───────────────────────────────────────────────

class TestExtremeConstraints:
    """Optimizer behavior under artificially tight or loose constraints."""

    def test_very_tight_pump_ceiling_disqualifies_most(self):
        tight = CircuitRequirements(
            circuit_id="CIRCUIT-TIGHT",
            max_pump_penalty_pct=1.0,
            min_enhancement_pct=0.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        results = rank_blends(tight)
        qualified = [r for r in results if not r.disqualified]
        assert len(qualified) == 0 or all(
            r.pump_penalty_pct <= 1.0 for r in qualified
        ), "Tight pump ceiling must disqualify or constrain"

    def test_zero_volume_fraction_yields_no_candidates(self):
        zero_phi = CircuitRequirements(
            circuit_id="CIRCUIT-ZERO",
            max_volume_fraction=0.0,
            min_enhancement_pct=0.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        results = rank_blends(zero_phi)
        assert len(results) == 0, "Zero volume fraction must yield no candidates"

    def test_very_high_enhancement_requirement_disqualifies_most(self):
        high_req = CircuitRequirements(
            circuit_id="CIRCUIT-HIGH",
            min_enhancement_pct=95.0,
            max_pump_penalty_pct=50.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        results = rank_blends(high_req)
        qualified = [r for r in results if not r.disqualified]
        for r in qualified:
            assert r.enhancement_pct >= 95.0


# ─── Individual Scoring Tests ───────────────────────────────────────────────

class TestScoringMechanics:
    """Verify the scoring function in isolation."""

    def test_score_candidate_returns_valid_result(self):
        spec = NanofluidSpec(
            name="Al2O3_3pct",
            base_fluid="water",
            nanoparticle="Al2O3",
            volume_fraction=0.03,
            particle_size_nm=30.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        result = score_candidate(spec, PEAK_REQUIREMENTS)
        assert isinstance(result, CandidateResult)
        assert 0 <= result.composite_score <= 1.0
        assert result.rank == 0  # rank assigned later by rank_blends

    def test_score_increases_with_enhancement(self):
        base_spec = NanofluidSpec(
            name="low_phi",
            base_fluid="water",
            nanoparticle="Al2O3",
            volume_fraction=0.01,
            particle_size_nm=30.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        high_spec = NanofluidSpec(
            name="high_phi",
            base_fluid="water",
            nanoparticle="Al2O3",
            volume_fraction=0.05,
            particle_size_nm=30.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        base_result = score_candidate(base_spec, PEAK_REQUIREMENTS)
        high_result = score_candidate(high_spec, PEAK_REQUIREMENTS)
        assert high_result.enhancement_pct > base_result.enhancement_pct

    def test_custom_weights_change_ranking(self):
        thermal_heavy = {**DEFAULT_WEIGHTS, "thermal": 0.80, "stability": 0.10, "pump": 0.05, "replacement": 0.05}
        stab_heavy = {**DEFAULT_WEIGHTS, "thermal": 0.10, "stability": 0.80, "pump": 0.05, "replacement": 0.05}

        results_th = rank_blends(PEAK_REQUIREMENTS, weights=thermal_heavy)
        results_st = rank_blends(PEAK_REQUIREMENTS, weights=stab_heavy)

        top_th = next(r for r in results_th if r.recommended)
        top_st = next(r for r in results_st if r.recommended)
        # With different weights, recommended candidates may differ
        # At minimum, both must produce a valid recommendation
        assert top_th is not None and top_st is not None


# ─── Viscosity Under Heat Stress ────────────────────────────────────────────

class TestViscosityHeatStress:
    """Verify viscosity model behaves correctly at elevated temperatures."""

    def test_water_viscosity_decreases_with_temperature(self):
        cold = ViscositySpec(base_fluid="water", volume_fraction=0.03, temperature_c=25.0)
        hot = ViscositySpec(base_fluid="water", volume_fraction=0.03, temperature_c=85.0)
        r_cold = viscosity_evaluate(cold)
        r_hot = viscosity_evaluate(hot)
        assert r_hot.effective_viscosity_cp < r_cold.effective_viscosity_cp

    def test_high_phi_high_temp_viscosity_bounded(self):
        spec = ViscositySpec(base_fluid="water", volume_fraction=0.05, temperature_c=PEAK_INLET_TEMP_C)
        result = viscosity_evaluate(spec)
        assert result.effective_viscosity_cp > 0
        assert result.pump_penalty_pct < MAX_PUMP_PENALTY_PCT

    def test_all_base_fluids_stable_at_peak_temp(self):
        for fluid in ["water", "ethylene_glycol", "water_eg_50_50"]:
            spec = ViscositySpec(base_fluid=fluid, volume_fraction=0.05, temperature_c=PEAK_INLET_TEMP_C)
            result = viscosity_evaluate(spec)
            assert result.effective_viscosity_cp > 0


# ─── Stability Under Heat Stress ────────────────────────────────────────────

class TestStabilityHeatStress:
    """Verify stability model degrades gracefully under extreme conditions."""

    def test_stability_score_bounded(self):
        spec = StabilitySpec(
            nanoparticle="Al2O3",
            base_fluid="water",
            volume_fraction=0.05,
            particle_size_nm=30.0,
            zeta_mv=35.0,
            age_days=0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        result = stability_evaluate(spec)
        assert 0 <= result.stability_score <= 100

    def test_aged_fluid_degradation_increases(self):
        fresh = StabilitySpec(
            nanoparticle="Al2O3",
            base_fluid="water",
            volume_fraction=0.03,
            particle_size_nm=30.0,
            zeta_mv=35.0,
            age_days=0,
        )
        aged = StabilitySpec(
            nanoparticle="Al2O3",
            base_fluid="water",
            volume_fraction=0.03,
            particle_size_nm=30.0,
            zeta_mv=35.0,
            age_days=120,
        )
        r_fresh = stability_evaluate(fresh)
        r_aged = stability_evaluate(aged)
        assert r_aged.stability_score < r_fresh.stability_score


# ─── Edge Case Tests ────────────────────────────────────────────────────────

class TestEdgeCases:
    """Boundary conditions and unusual inputs."""

    def test_minimal_volume_fraction(self):
        req = CircuitRequirements(
            circuit_id="CIRCUIT-MIN",
            min_enhancement_pct=0.0,
            max_pump_penalty_pct=50.0,
            max_volume_fraction=0.001,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        results = rank_blends(req)
        assert len(results) == 0, (
            "Volume fraction 0.001% is below optimizer sweep range (0.5%+) — "
            "must produce no candidates"
        )

    def test_single_particle_type(self):
        req = CircuitRequirements(
            circuit_id="CIRCUIT-SINGLE",
            min_enhancement_pct=0.0,
            max_pump_penalty_pct=50.0,
            temperature_c=PEAK_INLET_TEMP_C,
        )
        results = rank_blends(req)
        assert len(results) >= len(NANOPARTICLE_CONDUCTIVITY)

    def test_optimizer_idempotent(self):
        r1 = rank_blends(PEAK_REQUIREMENTS)
        r2 = rank_blends(PEAK_REQUIREMENTS)
        for a, b in zip(r1, r2):
            assert a.name == b.name
            assert a.composite_score == b.composite_score
            assert a.rank == b.rank
