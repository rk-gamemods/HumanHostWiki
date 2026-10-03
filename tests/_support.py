"""Private fixture roots for module workers and direct unittest invocation."""

import os
from pathlib import Path


def fixture_parent(label: str) -> Path:
    private = os.environ.get("HHWIKI_TEST_ROOT")
    # Module roots are already unique. Avoid another label directory on Windows.
    parent = Path(private) if private else Path(__file__).resolve().parents[1] / ".local" / label
    parent.mkdir(parents=True, exist_ok=True)
    return parent
