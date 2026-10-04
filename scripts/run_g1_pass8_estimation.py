"""Protected multiprocessing entry point for the G1-pass8 formal fixed480 estimation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from winai_loseai.experiments.g1_pass8_estimation import main
if __name__ == "__main__":
    raise SystemExit(main())
