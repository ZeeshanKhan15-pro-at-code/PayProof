"""Read-only scan of reachable Git blobs; never emit credential values or excerpts."""

import argparse
import json
import re
import subprocess
from pathlib import Path

TOKEN_PATTERNS = (
    ("OPENAI_STYLE_TOKEN", re.compile(r"\bsk-(?:proj-)?[A-Za-z0-9_-]{20,}\b")),
    ("HUGGINGFACE_STYLE_TOKEN", re.compile(r"\bhf_[A-Za-z0-9]{20,}\b")),
    (
        "GITHUB_STYLE_TOKEN",
        re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,})\b"),
    ),
    ("AWS_ACCESS_KEY_ID", re.compile(r"\b(?:AKIA|ASIA)[A-Z0-9]{16}\b")),
    (
        "PRIVATE_KEY",
        re.compile(r"-----BEGIN (?:RSA |EC |DSA |OPENSSH |ENCRYPTED )?PRIVATE KEY-----"),
    ),
)
ASSIGNMENT = re.compile(r"^\s*([A-Z][A-Z0-9_]*(?:KEY|TOKEN|PASSWORD|SECRET))\s*=\s*(.*?)\s*$")


def git(repo: Path, *args: str, data: bytes | None = None) -> bytes:
    return subprocess.run(
        ["git", "-C", str(repo), *args], input=data, capture_output=True, check=True
    ).stdout


def findings(text: str, path: str) -> list[tuple[int, str]]:
    """Return metadata only; environment literals remain candidate exposures."""
    results: set[tuple[int, str]] = set()
    for number, line in enumerate(text.splitlines(), start=1):
        for category, pattern in TOKEN_PATTERNS:
            if pattern.search(line):
                results.add((number, category))
        if Path(path).name.startswith(".env"):
            match = ASSIGNMENT.match(line)
            if match:
                value = match[2].split(" #", 1)[0].strip().strip("\"'")
                if value and not value.startswith(("$", "${")):
                    results.add((number, "NONEMPTY_ENV_SECRET_LITERAL"))
    return sorted(results)


def scan(repo: Path) -> dict[str, object]:
    objects = git(repo, "rev-list", "--objects", "--all").decode().splitlines()
    paths = {parts[0]: parts[1] for line in objects if len(parts := line.split(" ", 1)) == 2}
    inventory = (
        git(
            repo,
            "cat-file",
            "--batch-check=%(objectname) %(objecttype)",
            data=("\n".join(paths) + "\n").encode(),
        )
        .decode()
        .splitlines()
    )
    blobs = [line.split()[0] for line in inventory if line.endswith(" blob")]
    records = []
    binary_blobs = 0
    for blob in blobs:
        raw = git(repo, "cat-file", "blob", blob)
        if b"\x00" in raw:
            binary_blobs += 1
            continue
        hits = findings(raw.decode("utf-8", errors="replace"), paths[blob])
        if hits:
            commits = (
                git(repo, "log", "--all", "--reverse", "--format=%H", "--find-object=" + blob)
                .decode()
                .splitlines()
            )
            records.append(
                {
                    "path": paths[blob],
                    "blob": blob,
                    "first_reachable_commit": commits[0] if commits else None,
                    "findings": [{"line": line, "category": category} for line, category in hits],
                }
            )
    return {
        "scope": "all refs reachable via git rev-list --all; unique historical blobs; no secret values",
        "reachable_commits": len(git(repo, "rev-list", "--all").splitlines()),
        "unique_blobs_scanned": len(blobs),
        "binary_blobs_not_scanned": binary_blobs,
        "finding_blobs": records,
        "rotation_status": "OWNER_CONFIRMATION_REQUIRED" if records else "NO_PATTERN_FINDINGS",
        "limitations": "Pattern scan is not proof of absence; unreachable objects, reflogs, external copies and actual token validity/revocation are not checked.",
    }


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, default=Path("."))
    args = parser.parse_args()
    try:
        report = scan(args.repo)
    except (subprocess.CalledProcessError, OSError):
        raise SystemExit("History scan could not read Git objects; no raw output emitted") from None
    print(json.dumps(report, indent=2))
    if report["finding_blobs"]:
        raise SystemExit(2)  # Findings need owner triage; never assert revocation.


if __name__ == "__main__":
    main()
