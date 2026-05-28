# Bio-Inspired Flow Topology

This directory documents bio-inspired cooling channel geometries applied to Colossus 2 circuit design.

## Concepts Under Evaluation

### Murray's Law (Branching Optimization)
- Optimal pipe radius ratio at bifurcations: r_parent³ = r_child1³ + r_child2³.
- Minimizes viscous flow resistance across the entire circuit tree.
- Applied to: coolant distribution manifolds, chip-level micro-channel branching.

### Shark Skin (Riblet Surfaces)
- V-groove riblets aligned with flow direction reduce drag by 5–10%.
- Applied to: inner surface of primary coolant pipes in high-velocity zones.

### Leaf Vein (Hierarchical Networks)
- Main artery → secondary veins → capillary network.
- Ensures uniform flow distribution across all rack zones.
- Applied to: zone-level coolant distribution within ZONE-A through ZONE-D.

## Status

- [ ] Murray's law applied to manifold design (coordinate with `xai-colossus-cooling`).
- [ ] Riblet surface spec delivered to waterplant pipe vendor.
- [ ] Leaf vein topology validated via CFD simulation.
