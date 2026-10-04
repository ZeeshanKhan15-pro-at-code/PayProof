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
assert len(corpus.vendors) == 4 and len(corpus.requests) == 10
assert create_app(load_settings({})).test_client().get('/healthz').status_code == 200
from contextlib import redirect_stdout
from io import StringIO
from payproof.cli import main
output = StringIO()
with redirect_stdout(output):
    assert main(['demo', '--simulate-review']) == 0
assert 'STATE: VERIFY' in output.getvalue()
assert 'Trusted account ending: 3821' in output.getvalue()
assert 'Requested account ending: 9928' in output.getvalue()
print(json.dumps({'wheel': 'initialized', 'vendors': len(corpus.vendors), 'requests': len(corpus.requests)}))
"""
    subprocess.run(
        [sys.executable, "-I", "-c", program, str(wheel.resolve())],
        cwd=tempfile.gettempdir(),
        check=True,
    )


if __name__ == "__main__":
    main()
