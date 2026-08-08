#!/usr/bin/env bash
set -euo pipefail

ARTIFACT_DIR=".verification-artifacts"
mkdir -p "${ARTIFACT_DIR}"

python -m pip install --disable-pip-version-check pytest
python -m compileall -q \
  nanosphere_model.py \
  stability_model.py \
  viscosity_model.py

python -m pytest \
  test_nanosphere.py \
  tests/test_portfolio_truth_surface.py \
  --junitxml="${ARTIFACT_DIR}/pytest-junit.xml" \
  -q \
  | tee "${ARTIFACT_DIR}/pytest-core.txt"

python - <<'PY' | tee ".verification-artifacts/nanofluid-scenario.json"
import json
import math
from pathlib import Path

from nanosphere_model import (
    FluidBatch,
    NanofluidSpec,
    enhancement_pct,
    export_circuit_manifest,
)
from stability_model import StabilitySpec, evaluate as evaluate_stability
from viscosity_model import ViscositySpec, evaluate as evaluate_viscosity

spec = NanofluidSpec(
    name="bounded-alumina-water-scenario",
    base_fluid="water",
    nanoparticle="Al2O3",
    volume_fraction=0.03,
    particle_size_nm=30.0,
    particle_shape="sphere",
    temperature_c=30.0,
    circuit_id="SCENARIO-CIRCUIT-01",
)
batch = FluidBatch(
    batch_id="SCENARIO-BATCH-01",
    spec=spec,
    install_date="2026-01-01",
    age_days=30,
)
stability = evaluate_stability(
    StabilitySpec(
        nanoparticle=spec.nanoparticle,
        base_fluid=spec.base_fluid,
        volume_fraction=spec.volume_fraction,
        particle_size_nm=spec.particle_size_nm,
        zeta_mv=-35.0,
        age_days=batch.age_days,
        temperature_c=spec.temperature_c,
        circuit_id=spec.circuit_id,
        batch_id=batch.batch_id,
    )
)
viscosity = evaluate_viscosity(
    ViscositySpec(
        base_fluid=spec.base_fluid,
        volume_fraction=spec.volume_fraction,
        temperature_c=spec.temperature_c,
        circuit_id=spec.circuit_id,
    )
)
manifest_path = Path(".verification-artifacts/circuit-manifest.json")
manifest = export_circuit_manifest([batch], manifest_path)

maxwell = enhancement_pct(spec, model="maxwell")
hamilton = enhancement_pct(spec, model="hamilton_crosser")

assert maxwell > 0.0
assert hamilton > 0.0
assert 0.0 <= stability.stability_score <= 100.0
assert viscosity.pump_penalty_pct >= 0.0
assert manifest["evidence_state"] == "MODELED_SCENARIO_NOT_TELEMETRY"
assert manifest["circuits"][0]["batch_id"] == batch.batch_id

remaining_days = stability.estimated_remaining_days_to_monitor
receipt = {
    "schema": "glaciereq.nanofluid-bounded-scenario.v1",
    "evidence_state": "MODELED_SCENARIO_VERIFIED",
    "input": {
        "base_fluid": spec.base_fluid,
        "nanoparticle": spec.nanoparticle,
        "volume_fraction": spec.volume_fraction,
        "particle_size_nm": spec.particle_size_nm,
        "temperature_c": spec.temperature_c,
        "zeta_mv": -35.0,
        "age_days": batch.age_days,
    },
    "conductivity": {
        "maxwell_enhancement_pct": round(maxwell, 6),
        "hamilton_crosser_enhancement_pct": round(hamilton, 6),
        "modeled_effective_conductivity_w_mk": manifest["circuits"][0][
            "modeled_effective_conductivity_w_mk"
        ],
        "modeled_degradation_pct": manifest["circuits"][0][
            "modeled_degradation_pct"
        ],
    },
    "stability": {
        "score": stability.stability_score,
        "status": stability.status,
        "stokes_velocity_nm_s": stability.stokes_velocity_nm_s,
        "remaining_days_to_monitor": (
            "infinity" if math.isinf(remaining_days) else remaining_days
        ),
        "risk_factors": list(stability.risk_factors),
        "replacement_review_recommended": stability.replacement_review_recommended,
    },
    "viscosity": {
        "base_viscosity_at_temperature_cp": viscosity.base_viscosity_at_temperature_cp,
        "effective_viscosity_cp": viscosity.effective_viscosity_cp,
        "viscosity_ratio": viscosity.viscosity_ratio,
        "modeled_pump_penalty_pct": viscosity.pump_penalty_pct,
        "regime": viscosity.regime,
    },
    "manifest": {
        "path": str(manifest_path),
        "schema": manifest["schema"],
        "evidence_state": manifest["evidence_state"],
    },
    "limits": [
        "comparative model only",
        "no laboratory measurement",
        "no material certification",
        "no physical circuit telemetry",
        "no chemical dosing or magnetic actuation",
        "no measured thermal or cost improvement",
    ],
}
print(json.dumps(receipt, indent=2))
PY

python - <<'PY'
import hashlib
import json
import os
import platform
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

artifact_dir = Path(".verification-artifacts")
junit = artifact_dir / "pytest-junit.xml"
scenario = artifact_dir / "nanofluid-scenario.json"
manifest = artifact_dir / "circuit-manifest.json"

for path in (junit, scenario, manifest):
    if not path.exists() or path.stat().st_size == 0:
        raise SystemExit(f"Missing or empty verification output: {path}")

root = ET.parse(junit).getroot()
suites = root.findall("testsuite") if root.tag == "testsuites" else [root]
tests = sum(int(suite.attrib.get("tests", 0)) for suite in suites)
failures = sum(int(suite.attrib.get("failures", 0)) for suite in suites)
errors = sum(int(suite.attrib.get("errors", 0)) for suite in suites)
skipped = sum(int(suite.attrib.get("skipped", 0)) for suite in suites)
passed = tests - failures - errors - skipped
if tests < 1 or failures or errors:
    raise SystemExit(
        f"Invalid pytest receipt: tests={tests} failures={failures} errors={errors}"
    )

receipt = {
    "schema": "glaciereq.nanosphere.portfolio-core-receipt.v1",
    "generated_at": datetime.now(timezone.utc).isoformat(),
    "repository": os.environ.get(
        "GITHUB_REPOSITORY", "GlacierEQ/xai-colossus-nanosphere"
    ),
    "tested_commit_or_merge_ref": os.environ.get("GITHUB_SHA", "local"),
    "source_head_commit": os.environ.get(
        "GITHUB_HEAD_SHA", os.environ.get("GITHUB_SHA", "local")
    ),
    "python": platform.python_version(),
    "evidence_state": "BOUNDED_NANOFLUID_MODEL_TEST_VERIFIED",
    "tests": {
        "passed": passed,
        "total": tests,
        "failures": failures,
        "errors": errors,
        "skipped": skipped,
    },
    "verified": {
        "validated_model_inputs": True,
        "strict_conductivity_model_selection": True,
        "deterministic_blend_search": True,
        "capped_age_penalty_behavior": True,
        "same_temperature_pump_penalty_baseline": True,
        "atomic_modeled_manifest": True,
        "external_actions_executed": 0,
        "scenario_sha256": hashlib.sha256(scenario.read_bytes()).hexdigest(),
        "manifest_sha256": hashlib.sha256(manifest.read_bytes()).hexdigest(),
    },
    "private_related_repositories": {
        "alpha": {
            "repository": "GlacierEQ/xai-colossus-nanosphere-alpha",
            "inspected_commit": "1b39fae3277a034c48d62c957883fd5c3a3118ce",
            "state": "PRIVATE_SPECULATIVE_PHYSICS_EXPERIMENT_BLOCKED_CALIBRATION",
        },
        "omega": {
            "repository": "GlacierEQ/xai-colossus-nanosphere-omega",
            "inspected_commit": "ea089c1ec15add80bc1d9ff9290fb51652773561",
            "state": "PRIVATE_STATEFUL_CONTROL_SIMULATION_BLOCKED_AUTHORITY_AND_STATE_ISOLATION",
        },
    },
    "not_verified": [
        "laboratory measurements or material certification",
        "real circuit telemetry",
        "chemical dosing, magnetic recovery, or hardware actuation",
        "complete multiphase or non-Newtonian behavior",
        "corrosion, erosion, filtration, toxicology, or compatibility",
        "thermal or operating-cost improvement",
        "private Alpha or Omega composition",
        "physical-system safety",
    ],
}
(artifact_dir / "portfolio-core-receipt.json").write_text(
    json.dumps(receipt, indent=2) + "\n",
    encoding="utf-8",
)
print(json.dumps(receipt, indent=2))
PY
