# Fluid Models

This directory contains thermal conductivity models, viscosity curves, and mixing ratio specifications for Colossus 2 nanofluid circuits.

## Models Implemented

- **Maxwell Model** (`nanosphere_model.py`) — spherical particles, dilute suspension, validated for φ < 5%.
- **Hamilton-Crosser Model** (`nanosphere_model.py`) — extends Maxwell with shape factor n for cylinders, blades, platelets.

## Planned

- Bruggeman model (concentrated suspensions, φ > 5%).
- Temperature-dependent viscosity curves (Krieger–Dougherty).
- Mixing enthalpy tables for hybrid nanofluids (e.g. Al₂O₃ + graphene).

## Validation Benchmarks

| Fluid           | φ   | Predicted k (W/m·K) | Measured k   | Source      |
|----------------|-----|---------------------|-------------|------------|
| Al₂O₃/water    | 3%  | ~0.649              | 0.645–0.655 | Literature |
| graphene/water | 0.5%| ~0.656              | 0.650–0.670 | Literature |

*Populate with Colossus 2 measured data as circuits come online.*
