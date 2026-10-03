"""Repository tests, also executable as individual unittest modules."""

import os
from pathlib import Path
import sys

# Named modules import shared fixtures beside them (for example test_publish_gate).
sys.path.insert(0, str(Path(__file__).resolve().parent))

# Fixture repositories are copied while tests run. Newer Git starts automatic
# maintenance in the background after commits, and its lock files can appear and
# vanish mid-copy, so test processes and their Git children turn it off.
_count = int(os.environ.get("GIT_CONFIG_COUNT", "0"))
for _key, _value in (("gc.auto", "0"), ("maintenance.auto", "false")):
    os.environ[f"GIT_CONFIG_KEY_{_count}"] = _key
    os.environ[f"GIT_CONFIG_VALUE_{_count}"] = _value
    _count += 1
os.environ["GIT_CONFIG_COUNT"] = str(_count)
