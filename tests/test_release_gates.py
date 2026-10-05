"""Security-bearing tests for value-free historical credential assessment."""

import json
import secrets
import subprocess
from pathlib import Path

from scripts.check_credential_history import findings, scan


def git(repo, *args):
    return subprocess.run(["git", "-C", str(repo), *args], check=True, capture_output=True)


def test_history_scan_detects_removed_secret_without_exposing_it(tmp_path):
    git(tmp_path, "init")
    secret = "hf_" + secrets.token_hex(20)
    example = tmp_path / ".env.example"
    example.write_text("PAYPROOF_PROVIDER_API_KEY=" + secret + "\n")
    git(tmp_path, "add", ".env.example")
    git(
        tmp_path,
        "-c",
        "user.name=Synthetic QA",
        "-c",
        "user.email=qa@example.test",
        "commit",
        "-m",
        "Synthetic exposure",
    )
    example.write_text("PAYPROOF_PROVIDER_API_KEY=\n")
    git(tmp_path, "add", ".env.example")
    git(
        tmp_path,
        "-c",
        "user.name=Synthetic QA",
        "-c",
        "user.email=qa@example.test",
        "commit",
        "-m",
        "Clear example",
    )
    report = scan(tmp_path)
    rendered = json.dumps(report)
    assert secret not in rendered
    assert "NONEMPTY_ENV_SECRET_LITERAL" in rendered
    assert "HUGGINGFACE_STYLE_TOKEN" in rendered
    assert report["rotation_status"] == "OWNER_CONFIRMATION_REQUIRED"
    assert report["reachable_commits"] == 2
    assert report["finding_blobs"][0]["path"] == ".env.example"
    assert len(report["finding_blobs"]) == 1


def test_blank_examples_and_environment_references_are_not_exposures():
    assert (
        findings(
            "PAYPROOF_PROVIDER_API_KEY=\nPAYPROOF_SECRET_KEY=''\nKEY=${HOST_KEY}\n", ".env.example"
        )
        == []
    )
    assert findings("api_key = os.environ['PAYPROOF_PROVIDER_API_KEY']", "config.py") == []


def test_private_key_material_reports_category_only():
    result = findings("-----BEGIN PRIVATE KEY-----\nsynthetic\n", "private.pem")
    assert result == [(1, "PRIVATE_KEY")]


def test_binary_and_nonmatching_blobs_are_accounted_for(tmp_path):
    git(tmp_path, "init")
    (tmp_path / "image.bin").write_bytes(b"\x00synthetic")
    (tmp_path / "README.md").write_text("No credential literals.\n")
    git(tmp_path, "add", ".")
    git(
        tmp_path,
        "-c",
        "user.name=Synthetic QA",
        "-c",
        "user.email=qa@example.test",
        "commit",
        "-m",
        "Synthetic corpus",
    )
    report = scan(Path(tmp_path))
    assert report["unique_blobs_scanned"] == 2
    assert report["binary_blobs_not_scanned"] == 1
    assert report["finding_blobs"] == []
    assert report["rotation_status"] == "NO_PATTERN_FINDINGS"
    assert "unreachable" in report["limitations"]


def test_http_platform_denial_is_blocked_not_an_application_failure(monkeypatch, tmp_path):
    import errno

    from scripts.check_wheel import check_http

    def denied():
        raise PermissionError(errno.EPERM, "Synthetic platform socket denial")

    monkeypatch.setattr("scripts.check_wheel.socket.socket", denied)
    report = check_http({}, tmp_path)
    assert report["http_binding"] == "BLOCKED"
    assert report["errno"] == errno.EPERM


def test_other_socket_error_is_failed_not_infrastructure_abstention(monkeypatch, tmp_path):
    import errno

    from scripts.check_wheel import check_http

    def broken():
        raise OSError(errno.EMFILE, "Synthetic exhausted file descriptors")

    monkeypatch.setattr("scripts.check_wheel.socket.socket", broken)
    assert check_http({}, tmp_path)["http_binding"] == "FAILED"


def test_history_command_requires_owner_triage_and_outputs_no_secret(monkeypatch, capsys):
    import pytest

    from scripts.check_credential_history import main

    monkeypatch.setattr("sys.argv", ["check_credential_history"])
    monkeypatch.setattr(
        "scripts.check_credential_history.scan",
        lambda repo: {
            "finding_blobs": [{"path": ".env.example", "category": "NONEMPTY_ENV_SECRET_LITERAL"}]
        },
    )
    with pytest.raises(SystemExit) as stopped:
        main()
    assert stopped.value.code == 2
    assert json.loads(capsys.readouterr().out)["finding_blobs"][0]["path"] == ".env.example"
