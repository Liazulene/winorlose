"""Protected multiprocessing entry point for the G1-pass8 pilot."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from winai_loseai.experiments.g1_pass8 import main
if __name__ == "__main__":
    raise SystemExit(main())
