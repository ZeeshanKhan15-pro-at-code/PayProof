"""Public health/capabilities plus a gated minimal local operator workflow."""

import os
import secrets

from flask import Flask, Response, jsonify, request

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
            stage="operator_workflow" if settings.operator_token else "skeleton",
        )

    @app.get("/")
    def debug_index() -> Response:
        if request.accept_mimetypes.best == "text/html":
            return Response(status=302, headers={"Location": "/operator"})
        return jsonify(
            application="PayProof",
            stage="operator_workflow" if settings.operator_token else "skeleton",
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

    from payproof.operator_web import register_operator_workflow

    register_operator_workflow(app, settings)
    return app
