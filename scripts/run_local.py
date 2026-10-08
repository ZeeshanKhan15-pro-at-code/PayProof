"""Run a command with private local configuration; never execute shell file contents."""

import os
import subprocess
import sys
from pathlib import Path


def local_environment(path: Path, environ: dict[str, str]) -> dict[str, str]:
    result = dict(environ)
    if not path.exists():
        return result
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        name, sep, value = line.partition("=")
        if not sep or not name.startswith("PAYPROOF_") or not name.replace("_", "").isalnum():
            raise ValueError("Invalid private configuration; use NAME=value lines")
        result.setdefault(name, value)
    return result


def main() -> int:
    try:
        env = local_environment(Path(".env"), dict(os.environ))
    except (ValueError, OSError):
        print("Private configuration unreadable or malformed", file=sys.stderr)
        return 2
    command = sys.argv[1:] or [sys.executable, "-m", "payproof", "serve"]
    return subprocess.run(command, env=env, check=False).returncode


if __name__ == "__main__":
    raise SystemExit(main())
