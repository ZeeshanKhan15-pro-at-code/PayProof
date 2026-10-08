"""Private config and verification-runner regressions; no live requests."""

import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace

import pytest


def script(name):
    spec = importlib.util.spec_from_file_location(name, Path("scripts") / (name + ".py"))
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_local_defaults_are_not_shell_and_process_wins(tmp_path):
    module = script("run_local")
    p = tmp_path / "private"
    p.write_text("PAYPROOF_PROVIDER=featherless\nPAYPROOF_PROVIDER_MODEL=$(do-not-execute)\n")
    env = module.local_environment(p, {"PAYPROOF_PROVIDER": "openai"})
    assert env["PAYPROOF_PROVIDER"] == "openai"
    assert env["PAYPROOF_PROVIDER_MODEL"] == "$(do-not-execute)"
    p.write_text("export PAYPROOF_PROVIDER=bad\n")
    with pytest.raises(ValueError):
        module.local_environment(p, {})


def test_verification_runs_after_benchmark_failure_without_overwriting(tmp_path, monkeypatch):
    module = script("verify_foundation")
    calls = []

    def run(command, **kwargs):
        calls.append(command)
        return SimpleNamespace(returncode=1 if "payproof.heldout_benchmark" in command else 0)

    monkeypatch.setattr(module.subprocess, "run", run)
    out = tmp_path / "fresh"
    monkeypatch.setattr(module.sys, "argv", ["verify_foundation", str(out)])
    assert module.main() == 1
    results = json.loads((out / "gates.json").read_text())
    assert results["gold_heldout"]["status"] == "FAIL"
    assert results["build"]["status"] == results["package_smoke"]["status"] == "PASS"
    assert len(calls) == 10
    with pytest.raises(FileExistsError):
        module.main()
