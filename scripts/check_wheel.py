"""Prove the wheel imports and contains source-validated fixtures outside the repo."""

import subprocess
import sys
import tempfile
from pathlib import Path


def main() -> None:
    wheel = max(Path("dist").glob("payproof-*.whl"), key=lambda path: path.stat().st_mtime)
    program = """
import json
import sys
sys.path.insert(0, sys.argv[1])
import payproof
from payproof.config import load_settings
from payproof.fixtures import load_corpus
from payproof.web import create_app
assert '.whl/' in payproof.__file__, 'Smoke test did not import the wheel'
corpus = load_corpus()
assert len(corpus.vendors) == 3 and len(corpus.requests) == 9
assert create_app(load_settings({})).test_client().get('/healthz').status_code == 200
print(json.dumps({'wheel': 'initialized', 'vendors': len(corpus.vendors), 'requests': len(corpus.requests)}))
"""
    subprocess.run(
        [sys.executable, "-I", "-c", program, str(wheel.resolve())],
        cwd=tempfile.gettempdir(),
        check=True,
    )


if __name__ == "__main__":
    main()
