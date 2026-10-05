"""Install the wheel in a temporary target and smoke-test outside the checkout.

Uses the calling interpreter's installed dependencies, not a clean dependency
installation. Release gates must check a fresh pinned environment separately.
"""

import argparse
import errno
import json
import os
import secrets
import socket
import subprocess
import sys
import tempfile
import time
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener


def check_http(environment: dict[str, str], directory: Path) -> dict[str, object]:
    """Probe actual production listener; platform denial differs from app failure."""
    try:
        with socket.socket() as probe:
            probe.bind(("127.0.0.1", 0))
            port = int(probe.getsockname()[1])
    except OSError as error:
        return {
            "http_binding": "BLOCKED" if error.errno in (errno.EPERM, errno.EACCES) else "FAILED",
            "reason": type(error).__name__,
            "errno": error.errno,
        }
    production = dict(environment)
    production["PAYPROOF_ENV"] = "production"
    production["PAYPROOF_SECRET_KEY"] = secrets.token_urlsafe(48)
    with tempfile.TemporaryFile() as log:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "gunicorn",
                "--bind",
                f"127.0.0.1:{port}",
                "--workers",
                "1",
                "--threads",
                "2",
                "payproof.web:create_app()",
            ],
            cwd=directory,
            env=production,
            stdout=log,
            stderr=log,
        )
        try:
            opener = build_opener(ProxyHandler({}))
            deadline = time.monotonic() + 10
            while time.monotonic() < deadline:
                if process.poll() is not None:
                    return {
                        "http_binding": "FAILED",
                        "reason": "Gunicorn exited before health",
                        "exit_code": process.returncode,
                    }
                try:
                    with opener.open(f"http://127.0.0.1:{port}/healthz", timeout=1) as response:
                        health = json.loads(response.read(16384))
                        assert (
                            response.status == 200
                            and health["application"] == "PayProof"
                            and health["status"] == "ok"
                        )
                    with opener.open(f"http://127.0.0.1:{port}/", timeout=1) as response:
                        capabilities = json.loads(response.read(16384))
                        assert response.status == 200 and capabilities["writable"] is False
                    return {
                        "http_binding": "PASS",
                        "server": "installed_package_gunicorn",
                        "health_status": 200,
                        "capability_status": 200,
                        "writable": False,
                    }
                except (OSError, URLError):
                    time.sleep(0.1)
                except (ValueError, KeyError, AssertionError):
                    return {
                        "http_binding": "FAILED",
                        "reason": "Unexpected health/capability response",
                    }
            return {"http_binding": "FAILED", "reason": "Health deadline exceeded (10s)"}
        finally:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--http",
        action="store_true",
        help="Also check installed Gunicorn listener; exits 2 if platform-blocked, 1 if failed",
    )
    args = parser.parse_args()
    wheel = max(Path("dist").glob("payproof-*.whl"), key=lambda path: path.stat().st_mtime)
    program = """
import json
import sys
from pathlib import Path
from urllib.error import URLError
from urllib.request import ProxyHandler, build_opener
from importlib.metadata import distributions
site = Path(sys.argv[1]).resolve()
sys.path.insert(0, str(site))
import payproof
assert Path(payproof.__file__).resolve().is_relative_to(site), 'Imported checkout instead of installed package'
metadata = next(d for d in distributions(path=[str(site)]) if d.metadata['Name'] == 'payproof')
assert metadata.version == '0.1.0'
from payproof.config import load_settings
from payproof.fixtures import load_corpus
from payproof.web import create_app
corpus = load_corpus()
assert len(corpus.vendors) == 4 and len(corpus.requests) == 10
import secrets
settings = load_settings({'PAYPROOF_ENV': 'production', 'PAYPROOF_SECRET_KEY': secrets.token_urlsafe(48)})
app = create_app(settings)
assert app.test_client().get('/healthz').status_code == 200
assert app.test_client().get('/').json['writable'] is False
assert app.debug is False and app.config['SESSION_COOKIE_SECURE'] is True
from contextlib import redirect_stdout
from io import StringIO
from payproof.cli import main
output = StringIO()
with redirect_stdout(output):
    assert main(['demo', '--simulate-review']) == 0
assert 'STATE: VERIFY' in output.getvalue()
assert 'Trusted account ending: 3821' in output.getvalue()
assert 'Requested account ending: 9928' in output.getvalue()
assert 'STATE: VERIFIED' not in output.getvalue()
print(json.dumps({'wheel': 'installed_and_initialized', 'dependencies': 'existing_interpreter', 'vendors': len(corpus.vendors), 'requests': len(corpus.requests), 'production_wsgi_health': 200, 'http_binding': 'NOT_TESTED'}))
"""
    with tempfile.TemporaryDirectory(prefix="payproof-installed-wheel-") as temporary:
        site = Path(temporary) / "site"
        # Offline install of the application wheel; dependencies are checked by
        # imports in the subsequent process and remain a separate clean-install gate.
        subprocess.run(
            [
                sys.executable,
                "-m",
                "pip",
                "install",
                "--disable-pip-version-check",
                "--no-index",
                "--no-deps",
                "--no-compile",
                "--target",
                str(site),
                str(wheel.resolve()),
            ],
            cwd=temporary,
            check=True,
            capture_output=True,
        )
        subprocess.run([sys.executable, "-I", "-c", program, str(site)], cwd=temporary, check=True)
        environment = {
            key: value for key, value in os.environ.items() if not key.startswith("PAYPROOF_")
        }
        environment["PYTHONPATH"] = str(site)
        console = site / "bin" / "payproof"
        run = subprocess.run(
            [str(console), "check"],
            cwd=temporary,
            env=environment,
            check=True,
            capture_output=True,
            text=True,
        )
        if '"status": "initialized"' not in run.stdout:
            raise RuntimeError("Installed console entry point did not initialize")
        print('{"installed_console_entrypoint": "PASS", "provider_called": false}')
        if args.http:
            report = check_http(environment, Path(temporary))
            print(json.dumps(report))
            if report["http_binding"] != "PASS":
                raise SystemExit(2 if report["http_binding"] == "BLOCKED" else 1)


if __name__ == "__main__":
    main()
