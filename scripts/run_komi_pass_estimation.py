"""Protected multiprocessing entry point for the komi by pass estimation."""
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from winai_loseai.experiments.komi_pass_estimation import main
if __name__ == "__main__":
    raise SystemExit(main())
