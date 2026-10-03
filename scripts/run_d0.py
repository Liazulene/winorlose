"""Protected multiprocessing entry point for the isolated D0 diagnostic."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from winai_loseai.experiments.d0 import main

if __name__ == "__main__":
    raise SystemExit(main())
