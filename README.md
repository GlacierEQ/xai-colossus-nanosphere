# xAI Colossus Nanosphere — C++ Header-Only Compute Node Manager ⚛️

> **C++ header-only compute node management library for nanosphere-scale cluster nodes.**

[![C++](https://img.shields.io/badge/C++-17-00599C)]()
[![Python](https://img.shields.io/badge/Python-3.9+-blue)]()
[![Domain](https://img.shields.io/badge/Domain-HPC%20Compute-blue)]()

---

## 🎯 For Recruiters & Hiring Managers

This repository implements **xAI Colossus Nanosphere** — a lightweight, header-only C++ library for managing compute node memory layout and thread pinning across HPC node clusters. It demonstrates:

- **Header-only C++ architecture** (`.h`) for zero-dependency inclusion in C++ projects
- **NUMA node memory alignment** ensuring thread-to-core affinity for maximum memory bandwidth
- **Zero-allocation node allocation primitives** preventing heap fragmentation
- **Python test wrapper** validating C++ node initialization

**Why this matters**: High-performance compute engines rely on header-only C++ libraries to eliminate dynamic linkage overhead and guarantee memory alignment.

---

## 🔬 For Engineers & Technical Reviewers

### Core Components

| Component | Language | Purpose |
|---|---|---|
| `src/nanosphere_node.h` | C++ | Header-only C++ class for compute node memory management |
| `src/nanosphere_engine.cpp` | C++ | C++ driver implementing node lifecycle loops |
| `tests/` | Python | Nanosphere node allocation test suite |

---

## 🤖 ML/AI & Programmatic Mesh Integration

- **MCP Tool**: `nanosphere_node_status()` — node health queryable by HPC agents
- **Mastermind Sidecar**: Connected to APEX Highway mesh
- **SHA-256 Integrity**: Tracked in `.integrity/file_hashes.json`

---

## ⚡ Quick Start

```bash
python3 tests/test_nanosphere.py
```
