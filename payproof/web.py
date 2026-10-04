"""Read-only skeleton endpoints; no sensitive document or mutation routes."""

import os

from flask import Flask, Response, jsonify

from payproof.config import Settings, load_settings


def create_app(settings: Settings | None = None) -> Flask:
    settings = settings if settings is not None else load_settings(os.environ)
    app = Flask(__name__)
    app.config.update(
        DEBUG=False,
        TESTING=settings.environment == "test",
        MAX_CONTENT_LENGTH=100_000,
        SECRET_KEY=settings.secret_key.get_secret_value() if settings.secret_key else None,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Strict",
        SESSION_COOKIE_SECURE=settings.environment == "production",
    )

    @app.get("/healthz")
    def health() -> Response:
        # Liveness only; does not claim extraction, comparison, or storage readiness.
        return jsonify(status="ok", application="PayProof", stage="skeleton")

    @app.get("/")
    def debug_index() -> Response:
        return jsonify(
            application="PayProof",
            stage="skeleton",
            writable=False,
            implemented=[
                "contracts",
                "pasted_text_capture",
                "normalization",
                "synthetic_fixture_validation",
                "structured_extraction",
                "deterministic_comparison",
                "cli_review_workflow",
            ],
            pending=[
                "persistence",
                "human_verification",
                "operator_gate",
            ],
        )

    return app
