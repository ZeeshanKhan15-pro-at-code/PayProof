"""Run all independent gates; preserve benchmark outputs and never hide a failure."""

import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path


def main() -> int:
    output = (
        Path(sys.argv[1])
        if len(sys.argv) > 1
        else Path("/tmp") / ("payproof-verify-" + datetime.now(UTC).strftime("%Y%m%dT%H%M%S%f"))
    )
    output.mkdir(parents=True, exist_ok=False)
    python = sys.executable
    gates = {
        "lint": [python, "-m", "ruff", "check", "."],
        "format": [python, "-m", "ruff", "format", "--check", "."],
        "typecheck": [python, "-m", "mypy"],
        "tests": [python, "-m", "pytest", "-q"],
        "configuration": [python, "-m", "payproof", "check"],
        "gold_diagnostic": [
            python,
            "-m",
            "payproof",
            "benchmark",
            "--output",
            str(output / "diagnostic"),
        ],
        "gold_heldout": [
            python,
            "-m",
            "payproof.heldout_benchmark",
            "--evaluate-gold",
            "--output",
            str(output / "heldout"),
        ],
        "frozen_protocol": [python, "scripts/compile_heldout.py"],
        "build": [python, "-m", "build", "--no-isolation"],
        "package_smoke": [python, "scripts/check_wheel.py"],
    }
    results = {}
    for name, command in gates.items():
        code = subprocess.run(command, check=False).returncode
        results[name] = {
            "status": "PASS" if code == 0 else "FAIL",
            "exit_code": code,
            "command": command,
        }
    (output / "gates.json").write_text(json.dumps(results, indent=2) + "\n")
    print(json.dumps({"output": str(output), "gates": results}, indent=2))
    return int(any(item["exit_code"] != 0 for item in results.values()))


if __name__ == "__main__":
    raise SystemExit(main())
