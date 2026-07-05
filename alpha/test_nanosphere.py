"""Tests for xai-colossus-nanosphere."""
import sys, os, unittest
sys.path.insert(0, os.path.dirname(__file__))

from nanosphere_model import NanofluidSpec, enhancement_pct, NANOPARTICLE_CONDUCTIVITY
from stability_model import StabilitySpec, evaluate as stability_eval
from viscosity_model import ViscositySpec, pump_penalty_pct

class TestNanosphereModel(unittest.TestCase):
    def test_nanoparticle_conductivity_keys(self):
        self.assertIn("Al2O3", NANOPARTICLE_CONDUCTIVITY)
        self.assertIn("graphene", NANOPARTICLE_CONDUCTIVITY)

    def test_enhancement_pct_returns_positive(self):
        spec = NanofluidSpec(name="test", base_fluid="water", nanoparticle="Al2O3", volume_fraction=0.03, particle_size_nm=50)
        self.assertGreater(enhancement_pct(spec), 0)

    def test_enhancement_graphene_gt_alumina(self):
        g = enhancement_pct(NanofluidSpec(name="g", base_fluid="water", nanoparticle="graphene", volume_fraction=0.03, particle_size_nm=50))
        a = enhancement_pct(NanofluidSpec(name="a", base_fluid="water", nanoparticle="Al2O3", volume_fraction=0.03, particle_size_nm=50))
        self.assertGreater(g, a)

class TestStabilityModel(unittest.TestCase):
    def test_stability_score_range(self):
        spec = StabilitySpec(nanoparticle="Al2O3", base_fluid="water", volume_fraction=0.03, particle_size_nm=50, zeta_mv=-35.0, age_days=30)
        result = stability_eval(spec)
        self.assertGreaterEqual(result.stability_score, 0)
        self.assertLessEqual(result.stability_score, 100)
        self.assertEqual(result.status, "stable")

    def test_low_zeta_less_stable(self):
        high_zeta = stability_eval(StabilitySpec(nanoparticle="Al2O3", base_fluid="water", volume_fraction=0.03, particle_size_nm=50, zeta_mv=-45.0, age_days=30))
        low_zeta = stability_eval(StabilitySpec(nanoparticle="Al2O3", base_fluid="water", volume_fraction=0.03, particle_size_nm=50, zeta_mv=-10.0, age_days=30))
        self.assertGreater(high_zeta.stability_score, low_zeta.stability_score)

class TestViscosityModel(unittest.TestCase):
    def test_pump_penalty_calculated(self):
        spec = ViscositySpec(base_fluid="water", volume_fraction=0.03, temperature_c=30.0)
        result = pump_penalty_pct(spec)
        self.assertIsInstance(result, float)

    def test_higher_fraction_increases_penalty(self):
        low = pump_penalty_pct(ViscositySpec(base_fluid="water", volume_fraction=0.01, temperature_c=30.0))
        high = pump_penalty_pct(ViscositySpec(base_fluid="water", volume_fraction=0.08, temperature_c=30.0))
        self.assertGreater(high, low)

if __name__ == "__main__":
    unittest.main(verbosity=2)
