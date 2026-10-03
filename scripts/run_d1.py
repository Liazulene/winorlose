"""Protected multiprocessing entry point for the D1 cost calibration."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from winai_loseai.experiments.d1 import main
if __name__ == "__main__":
    raise SystemExit(main())
