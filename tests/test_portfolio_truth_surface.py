from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = ROOT / "README.md"

REQUIRED_PATHS = (
    "nanosphere_model.py",
    "stability_model.py",
    "viscosity_model.py",
    "test_nanosphere.py",
    "tests/test_portfolio_truth_surface.py",
    "scripts/ci/verify_portfolio_core.sh",
)

FORBIDDEN_STALE_CLAIMS = (
    "src/nanosphere_node.h",
    "src/nanosphere_engine.cpp",
    "C++ Header-Only Compute Node Manager",
    "NUMA node memory alignment",
    "Zero-allocation node allocation primitives",
    "nanosphere_node_status()",
    "Connected to APEX Highway mesh",
)


def test_readme_points_to_present_model_paths() -> None:
    text = README.read_text(encoding="utf-8")

    for relative_path in REQUIRED_PATHS:
        assert (ROOT / relative_path).exists(), relative_path
        assert relative_path in text


def test_readme_preserves_non_affiliation_and_model_boundaries() -> None:
    text = README.read_text(encoding="utf-8")

    assert "not affiliated with xAI" in text
    assert "not evidence of deployment" in text
    assert "comparative estimates" in text
    assert "not laboratory measurements" in text
    assert "MODELED_SCENARIO_NOT_TELEMETRY" in text
    assert "does not prove that another repository consumed it" in text


def test_private_alpha_and_omega_are_preserved_but_excluded() -> None:
    text = README.read_text(encoding="utf-8")

    assert "1b39fae3277a034c48d62c957883fd5c3a3118ce" in text
    assert "ea089c1ec15add80bc1d9ff9290fb51652773561" in text
    assert "not** counted as verified components" in text
    assert "No repository is deleted, collapsed" in text


def test_stale_cpp_and_mesh_claims_do_not_return() -> None:
    text = README.read_text(encoding="utf-8")

    for stale_claim in FORBIDDEN_STALE_CLAIMS:
        assert stale_claim not in text


def test_manifest_code_records_modeled_not_telemetry_state() -> None:
    source = (ROOT / "nanosphere_model.py").read_text(encoding="utf-8")

    assert '"schema": "glaciereq.nanofluid-circuit-manifest.v1"' in source
    assert '"evidence_state": "MODELED_SCENARIO_NOT_TELEMETRY"' in source
    assert "os.replace(temporary, destination)" in source


def test_public_model_contains_no_actuation_claims() -> None:
    combined = "\n".join(
        (ROOT / path).read_text(encoding="utf-8")
        for path in (
            "nanosphere_model.py",
            "stability_model.py",
            "viscosity_model.py",
        )
    )

    assert "Ingesting stabilizer" not in combined
    assert "Deploying recovery pulse" not in combined
    assert "Demanding magnetic sweep" not in combined
    assert "dosing_pump_active" not in combined
    assert "electromagnet_tesla" not in combined
