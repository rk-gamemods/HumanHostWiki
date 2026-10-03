"""Let named unittest modules import the shared fixtures beside them."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parent))
