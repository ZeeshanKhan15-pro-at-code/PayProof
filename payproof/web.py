"""Public health/capabilities plus a gated minimal local operator workflow."""

import os
import secrets

from flask import Flask, Response, jsonify, render_template, request
from werkzeug.middleware.dispatcher import DispatcherMiddleware

from payproof.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings if settings is not None else load_settings(os.environ)
    app = Flask(__name__)
    app.config.update(
        DEBUG=False,
        TESTING=settings.environment == "test",
        MAX_CONTENT_LENGTH=100_000,
        SECRET_KEY=settings.secret_key.get_secret_value()
        if settings.secret_key
        else secrets.token_urlsafe(48),
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=settings.environment == "production",
    )

    @app.get("/healthz")
    def health() -> Response:
        # Liveness only; does not claim extraction, comparison, or storage readiness.
        return jsonify(
            status="ok",
            application="PayProof",
            stage="public_workspace",
            operator_configured=settings.operator_token is not None,
        )

    @app.get("/readyz")
    def readiness() -> tuple[Response, int]:
        import sqlite3

        from payproof.storage import SQLiteStore, WorkflowError

        available = False
        try:
            database = SQLiteStore(settings.data_dir / "payproof.sqlite3")
            try:
                available = database.db.execute("SELECT 1").fetchone()[0] == 1
            finally:
                database.close()
        except (sqlite3.Error, OSError, WorkflowError):
            pass
        ready = available
        return jsonify(
            status="ready" if ready else "not_ready",
            storage=available,
            operator_configured=settings.operator_token is not None,
            extraction_mode=settings.extraction_mode,
            public_live_enabled=settings.public_live_enabled,
            provider_connectivity="NOT_CHECKED",
            scope="local_configuration_and_storage",
        ), 200 if ready else 503

    @app.get("/")
    def debug_index() -> Response:
        if request.accept_mimetypes.best == "text/html":
            return Response(
                render_template("public_landing.html", public_live=settings.public_live_enabled),
                mimetype="text/html",
            )
        return jsonify(
            application="PayProof",
            stage="public_workspace",
            public_workspace_url="/workspace/",
            public_live_enabled=settings.public_live_enabled,
            writable=settings.operator_token is not None,
            operator_url="/operator",
            implemented=[
                "contracts",
                "pasted_text_capture",
                "normalization",
                "synthetic_fixture_validation",
                "structured_extraction",
                "deterministic_comparison",
                "cli_review_workflow",
                "sqlite_persistence",
                "gated_web_workflow",
                "explicit_human_verification",
            ],
            pending=[
                "configure_operator_gate"
                if settings.operator_token is None
                else "multi_user_identity",
            ],
        )

    @app.after_request
    def public_headers(response: Response) -> Response:
        if request.path in {"/", "/healthz", "/readyz"}:
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    from payproof.operator_web import register_operator_workflow

    register_operator_workflow(app, settings)
    from payproof.public_workspace import create_public_app

    public_app = create_public_app(settings, str(app.config["SECRET_KEY"]))
    app.wsgi_app = DispatcherMiddleware(app.wsgi_app, {"/workspace": public_app})  # type: ignore[method-assign]
    return app
