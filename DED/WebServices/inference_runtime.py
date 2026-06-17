from __future__ import annotations

"""
Backward-compatible shim.

The active decision / inference logic now lives in `decision_runtime.py`.
This file is kept so existing imports do not break while the rest of the
project migrates to the dedicated decision module.
"""

try:
    from .decision_runtime import *  # noqa: F401,F403
except ImportError:
    from decision_runtime import *  # type: ignore # noqa: F401,F403
