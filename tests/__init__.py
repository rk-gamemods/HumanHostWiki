"""Repository tests, also executable as individual unittest modules."""

from pathlib import Path
import sys

# Named modules import shared fixtures beside them (for example test_publish_gate).
sys.path.insert(0, str(Path(__file__).resolve().parent))
