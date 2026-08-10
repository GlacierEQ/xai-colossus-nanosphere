"""Unittest bridge for nanosphere — drives shipped circuit_optimizer + model."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from circuit_optimizer import (  # noqa: E402
    CircuitRequirements,
    rank_blends,
    MAX_ENHANCEMENT_PCT,
)
from nanosphere_model import (  # noqa: E402
    DEGRADATION_HALFLIFE,
    DEGRADATION_HALFLIFE_DAYS,
    NanofluidSpec,
    enhancement_pct,
    maxwell_effective_conductivity,
    NANOPARTICLE_CONDUCTIVITY,
)


class NanosphereModelTests(unittest.TestCase):
    def test_halflife_alias_matches_days_table(self) -> None:
        self.assertEqual(DEGRADATION_HALFLIFE, DEGRADATION_HALFLIFE_DAYS)
        self.assertIn("Al2O3", DEGRADATION_HALFLIFE)

    def test_maxwell_conductivity_positive(self) -> None:
        for particle in NANOPARTICLE_CONDUCTIVITY:
            spec = NanofluidSpec(
                name=f"t-{particle}",
                base_fluid="water",
                nanoparticle=particle,
                volume_fraction=0.02,
                particle_size_nm=40.0,
            )
            k = maxwell_effective_conductivity(spec)
            self.assertGreater(k, 0.0, particle)

    def test_enhancement_bounded(self) -> None:
        spec = NanofluidSpec(
            name="t-al2o3",
            base_fluid="water",
            nanoparticle="Al2O3",
            volume_fraction=0.03,
            particle_size_nm=40.0,
        )
        pct = enhancement_pct(spec)
        self.assertGreaterEqual(pct, 0.0)
        self.assertLessEqual(pct, MAX_ENHANCEMENT_PCT * 2)  # physical room above score cap


class NanosphereOptimizerTests(unittest.TestCase):
    def setUp(self) -> None:
        self.reqs = CircuitRequirements(
            circuit_id="CIRCUIT-UNITTEST",
            base_fluid="water",
            min_enhancement_pct=1.0,
            max_pump_penalty_pct=40.0,
            max_volume_fraction=0.05,
            min_stability_score=20.0,
            min_halflife_days=30,
            temperature_c=60.0,
        )

    def test_rank_blends_nonempty(self) -> None:
        results = rank_blends(self.reqs)
        self.assertGreater(len(results), 0)

    def test_all_particles_represented(self) -> None:
        results = rank_blends(self.reqs)
        found = {r.nanoparticle for r in results}
        for particle in NANOPARTICLE_CONDUCTIVITY:
            self.assertIn(particle, found)

    def test_qualified_scores_monotonic(self) -> None:
        results = rank_blends(self.reqs)
        qualified = [r.composite_score for r in results if not r.disqualified]
        for i in range(len(qualified) - 1):
            self.assertGreaterEqual(qualified[i], qualified[i + 1])


if __name__ == "__main__":
    unittest.main()
