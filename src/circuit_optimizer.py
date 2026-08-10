"""Re-export root circuit_optimizer for package layout."""
from __future__ import annotations
import importlib.util
import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[1]
_spec = importlib.util.spec_from_file_location("_ns_circuit_optimizer", _root / "circuit_optimizer.py")
_mod = importlib.util.module_from_spec(_spec)
sys.modules[_spec.name] = _mod
_spec.loader.exec_module(_mod)
globals().update({k: getattr(_mod, k) for k in dir(_mod) if not k.startswith("__")})
