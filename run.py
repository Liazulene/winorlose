#!/usr/bin/env python
"""Single-command entry point for the WinAI/LoseAI 5x5 MVP.

Usage examples (from the repo root, with the `models` environment):
    python run.py test
    python run.py smoke-random --games-per-combo 25
    python run.py smoke-mcts  --games-per-pair 2
    python run.py batch --batch B --games 5600
    python run.py replay outputs/smoke_mcts
    python run.py summary outputs/smoke_mcts
"""

import os
import sys

_HERE = os.path.dirname(os.path.abspath(__file__))
_SRC = os.path.join(_HERE, "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)

from winai_loseai.cli import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())
