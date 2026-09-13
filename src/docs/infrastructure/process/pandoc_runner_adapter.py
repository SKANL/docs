from __future__ import annotations

import subprocess
from collections.abc import Sequence


class SubprocessPandocRunner:
    """Infrastructure implementation of the pandoc execution port."""

    def run(self, args: Sequence[str], *, check: bool, timeout: int) -> None:
        subprocess.run(args, check=check, timeout=timeout)
