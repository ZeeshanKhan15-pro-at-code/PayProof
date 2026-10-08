"""Isolated temporary public workflow and a persistent anonymous-provider call budget."""

import re
import shutil
import sqlite3
import time
from pathlib import Path

from flask import Flask

from payproof.config import Settings
from payproof.operator_web import register_operator_workflow
from payproof.storage import WorkflowError

SESSION_LIFETIME = 1800
MAX_PUBLIC_SESSIONS = 64


def cleanup_sessions(root: Path) -> None:
    """Only generated public session directories; never canonical operator data."""
    if root.is_symlink():
        raise WorkflowError("public storage must not be a symlink")
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    for folder in root.iterdir():
        if (
            folder.is_symlink()
            or not folder.is_dir()
            or not re.fullmatch(r"[a-f0-9]{32}", folder.name)
        ):
            continue
        if folder.stat().st_mtime < time.time() - SESSION_LIFETIME:
            shutil.rmtree(folder)


def reserve_live_call(settings: Settings) -> None:
    """Global lifetime call ceiling across sessions/restarts; failed calls count too."""
    if not settings.public_live_enabled:
        raise WorkflowError("public live extraction is disabled")
    path = settings.data_dir / "public-live-budget.sqlite3"
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    if path.is_symlink():
        raise WorkflowError("public budget store must not be a symlink")
    db = sqlite3.connect(path, isolation_level=None, timeout=5)
    try:
        path.chmod(0o600)
        db.execute(
            "CREATE TABLE IF NOT EXISTS budget (id INTEGER PRIMARY KEY CHECK(id=1), used INTEGER NOT NULL CHECK(used>=0))"
        )
        db.execute("BEGIN IMMEDIATE")
        db.execute("INSERT OR IGNORE INTO budget VALUES (1,0)")
        used = db.execute("SELECT used FROM budget WHERE id=1").fetchone()[0]
        if used >= settings.public_live_max_calls:
            db.execute("ROLLBACK")
            raise WorkflowError("public extraction budget exhausted; no provider request made")
        db.execute("UPDATE budget SET used=used+1 WHERE id=1")
        db.execute("COMMIT")
    finally:
        db.close()


def create_public_app(settings: Settings, signing_key: str) -> Flask:
    app = Flask(__name__)
    app.config.update(
        DEBUG=False,
        TESTING=settings.environment == "test",
        MAX_CONTENT_LENGTH=100_000,
        SECRET_KEY=signing_key,
        SESSION_COOKIE_NAME="payproof_public",
        SESSION_COOKIE_PATH="/workspace",
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=settings.environment == "production",
    )
    # Disabled public AI never forwards sources or credentials to a provider.
    public_settings = settings.model_copy(
        update={"extraction_mode": "live" if settings.public_live_enabled else "disabled"}
    )
    register_operator_workflow(app, public_settings, public=True)
    return app
