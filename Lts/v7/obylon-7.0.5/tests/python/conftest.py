from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
BRAIN = ROOT / "src" / "brain"
if str(BRAIN) not in sys.path:
    sys.path.insert(0, str(BRAIN))
