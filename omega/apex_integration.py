# Omega (How) — Controllers | Alpha (What) — Pure Physics | 1337.
"""
apex_integration.py — Cooling APEX Loop Nanosphere Integration
GlacierEQ APEX Stack | APEX Architecture

Wires nanosphere_model thermal conductivity calculations into the
Colossus 2 cooling APEX orchestrator loop.  Per-zone conductivity_factor
exports enable the cooling orchestrator to adjust pump rates, coolant
temperatures, and airflow in real time.

Outputs:
  - conductivity_factor per zone (0.0–1.0, 1.0 = fresh fluid)
  - circuit_manifest.json for cooling orchestrator consumption
  - zone health status with replacement flags

Interface contract:
  - Consumes: list of zone definitions (circuit_id, nanoparticle, volume_fraction, age_days)
  - Produces: dict with per-zone conductivity_factor + manifest for downstream
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
import json
import datetime
import logging
import os

from nanosphere_model import (
    NanofluidSpec,
    FluidBatch,
    maxwell_effective_conductivity,
    enhancement_pct,
    DEGRADATION_HALFLIFE,
)
from degradation.degradation_model import BatchLifecycle, FleetLifecycleManager


logger = logging.getLogger("apex_integration")

CONDUCTIVITY_FACTOR_FRESH = 1.0
CONDUCTIVITY_FACTOR_CRITICAL = 0.85
ZONE_STATUS_HEALTHY = "healthy"
ZONE_STATUS_WARNING = "warning"
ZONE_STATUS_CRITICAL = "critical"


@dataclass
class ZoneDefinition:
    """Input: a single cooling zone's nanofluid configuration."""
    zone_id: str
    circuit_id: str
    nanoparticle: str
    base_fluid: str = "water"
    volume_fraction: float = 0.03
    particle_size_nm: float = 30.0
    fresh_conductivity_w_mk: Optional[float] = None
    age_days: int = 0
    batch_id: Optional[str] = None
    install_date: Optional[str] = None


@dataclass
class ZoneConductivity:
    """Output: per-zone conductivity state for the cooling orchestrator."""
    zone_id: str
    circuit_id: str
    batch_id: Optional[str]
    nanoparticle: str
    volume_fraction_pct: float
    fresh_conductivity_w_mk: float
    current_conductivity_w_mk: float
    conductivity_factor: float
    enhancement_pct_over_base: float
    degradation_pct: float
    days_until_replacement: float
    zone_status: str
    replacement_flag: bool


def compute_zone_conductivity(zone: ZoneDefinition) -> ZoneConductivity:
    """
    Compute current conductivity and factor for a single zone.

    Uses Maxwell model for fresh conductivity and exponential decay
    for age-based degradation.
    """
    spec = NanofluidSpec(
        name=f"{zone.zone_id}_{zone.nanoparticle}",
        base_fluid=zone.base_fluid,
        nanoparticle=zone.nanoparticle,
        volume_fraction=zone.volume_fraction,
        particle_size_nm=zone.particle_size_nm,
        circuit_id=zone.circuit_id,
    )

    if zone.fresh_conductivity_w_mk is not None:
        fresh_k = zone.fresh_conductivity_w_mk
    else:
        fresh_k = maxwell_effective_conductivity(spec)

    half_life = DEGRADATION_HALFLIFE.get(zone.nanoparticle, 120)
    batch_lifecycle = BatchLifecycle(
        batch_id=zone.batch_id or f"{zone.zone_id}_batch",
        circuit_id=zone.circuit_id,
        nanoparticle=zone.nanoparticle,
        half_life_days=half_life,
        fresh_conductivity_w_mk=fresh_k,
        install_date=zone.install_date or datetime.date.today().isoformat(),
        age_days=zone.age_days,
    )

    factor = batch_lifecycle.conductivity_factor()
    current_k = batch_lifecycle.effective_conductivity()
    days_left = batch_lifecycle.days_until_replacement()

    from nanosphere_model import BASE_FLUID_CONDUCTIVITY
    base_k = BASE_FLUID_CONDUCTIVITY.get(zone.base_fluid, 0.613)
    enh_pct = (current_k - base_k) / base_k * 100
    deg_pct = (1.0 - factor) * 100

    if factor <= CONDUCTIVITY_FACTOR_CRITICAL:
        status = ZONE_STATUS_CRITICAL
    elif factor <= 0.90:
        status = ZONE_STATUS_WARNING
    else:
        status = ZONE_STATUS_HEALTHY

    return ZoneConductivity(
        zone_id=zone.zone_id,
        circuit_id=zone.circuit_id,
        batch_id=batch_lifecycle.batch_id,
        nanoparticle=zone.nanoparticle,
        volume_fraction_pct=round(zone.volume_fraction * 100, 2),
        fresh_conductivity_w_mk=round(fresh_k, 4),
        current_conductivity_w_mk=round(current_k, 4),
        conductivity_factor=round(factor, 6),
        enhancement_pct_over_base=round(enh_pct, 2),
        degradation_pct=round(deg_pct, 2),
        days_until_replacement=round(days_left, 1),
        zone_status=status,
        replacement_flag=factor <= CONDUCTIVITY_FACTOR_CRITICAL,
    )


def run_apex_loop(
    zones: List[ZoneDefinition],
    manifest_path: str = "integration/circuit_manifest.json",
) -> dict:
    """
    Execute one iteration of the APEX cooling loop integration.

    Computes conductivity_factor for each zone, identifies zones needing
    attention, and exports circuit_manifest.json for the cooling orchestrator.

    Returns dict with per-zone results and fleet summary.
    """
    logger.info("apex_loop_start zones=%d", len(zones))

    zone_results: List[ZoneConductivity] = []
    for zone in zones:
        result = compute_zone_conductivity(zone)
        zone_results.append(result)
        logger.info(
            "zone_computed zone=%s factor=%.4f status=%s replacement=%s",
            result.zone_id, result.conductivity_factor, result.zone_status, result.replacement_flag,
        )

    critical_zones = [z for z in zone_results if z.zone_status == ZONE_STATUS_CRITICAL]
    warning_zones = [z for z in zone_results if z.zone_status == ZONE_STATUS_WARNING]

    manifest = _build_manifest(zone_results, critical_zones, warning_zones, manifest_path)

    logger.info(
        "apex_loop_complete zones=%d critical=%d warnings=%d",
        len(zone_results), len(critical_zones), len(warning_zones),
    )

    return {
        "zones": zone_results,
        "critical_count": len(critical_zones),
        "warning_count": len(warning_zones),
        "fleet_avg_conductivity_factor": round(
            sum(z.conductivity_factor for z in zone_results) / max(len(zone_results), 1), 6
        ),
        "manifest_path": manifest_path,
    }


def _build_manifest(
    zone_results: List[ZoneConductivity],
    critical_zones: List[ZoneConductivity],
    warning_zones: List[ZoneConductivity],
    path: str,
) -> dict:
    """Build and persist circuit_manifest.json for cooling orchestrator."""
    manifest = {
        "generated_at": datetime.datetime.utcnow().isoformat() + "Z",
        "apex_loop_version": "1.0.0",
        "fleet_summary": {
            "total_zones": len(zone_results),
            "critical_zones": len(critical_zones),
            "warning_zones": len(warning_zones),
            "healthy_zones": len(zone_results) - len(critical_zones) - len(warning_zones),
            "avg_conductivity_factor": round(
                sum(z.conductivity_factor for z in zone_results) / max(len(zone_results), 1), 6
            ),
        },
        "zones": [
            {
                "zone_id": z.zone_id,
                "circuit_id": z.circuit_id,
                "batch_id": z.batch_id,
                "nanoparticle": z.nanoparticle,
                "volume_fraction_pct": z.volume_fraction_pct,
                "fresh_conductivity_w_mk": z.fresh_conductivity_w_mk,
                "current_conductivity_w_mk": z.current_conductivity_w_mk,
                "conductivity_factor": z.conductivity_factor,
                "enhancement_pct_over_base": z.enhancement_pct_over_base,
                "degradation_pct": z.degradation_pct,
                "days_until_replacement": z.days_until_replacement,
                "zone_status": z.zone_status,
                "replacement_flag": z.replacement_flag,
            }
            for z in zone_results
        ],
        "replacement_required": [
            {
                "zone_id": z.zone_id,
                "circuit_id": z.circuit_id,
                "batch_id": z.batch_id,
                "conductivity_factor": z.conductivity_factor,
                "degradation_pct": z.degradation_pct,
            }
            for z in critical_zones
        ],
    }

    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w") as f:
        json.dump(manifest, f, indent=2)
    logger.info("manifest_written path=%s zones=%d", path, len(zone_results))
    return manifest


def load_zone_definitions_from_fleet(manager: FleetLifecycleManager) -> List[ZoneDefinition]:
    """
    Convert a FleetLifecycleManager's registered batches into ZoneDefinitions
    for APEX loop consumption.
    """
    zones = []
    for batch in manager.batches.values():
        spec = batch
        zones.append(ZoneDefinition(
            zone_id=f"zone_{batch.circuit_id}",
            circuit_id=batch.circuit_id,
            nanoparticle=batch.nanoparticle,
            volume_fraction=0.03,
            fresh_conductivity_w_mk=batch.fresh_conductivity_w_mk,
            age_days=batch.age_days,
            batch_id=batch.batch_id,
            install_date=batch.install_date,
        ))
    return zones
