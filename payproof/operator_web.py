"""Small server-rendered adapter to existing durable workflow commands."""

import secrets
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from threading import Lock
from typing import cast
from urllib.parse import urlsplit
from uuid import UUID, uuid4

from flask import Flask, abort, g, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException
from werkzeug.wrappers import Response

from payproof.cases import start_case
from payproof.config import Settings
from payproof.documents import capture_text
from payproof.instruction_safety import extracted_keys, observation_key, source_inventory
from payproof.normalization import canonical_iban
from payproof.schemas import (
    EVIDENCE_FIELDS,
    NormalizedPaymentIdentity,
    SourceDocument,
    SourceKind,
    TrustedCallbackContact,
    TrustedVendorRecord,
    TrustProvenance,
)
from payproof.secret_guard import reject_configured_secrets
from payproof.storage import SQLiteStore, WorkflowError
from payproof.workflow_contracts import CaseInputs, IndependentCheckAction

# Presentation-only descriptions: all decision logic remains in the comparator.
REASON_EXPLANATIONS = {
    "BASELINE_UNAVAILABLE": "There is no prior trusted vendor baseline available for this comparison.",
    "BASELINE_INVALID": "The trusted baseline does not provide a valid supported destination.",
    "EVIDENCE_INVALID": "The extracted destination evidence does not support a reliable comparison.",
    "REVIEW_REQUIRED": "Original source instructions have not received explicit human source review.",
    "DESTINATION_MISSING": "A required destination is absent from trusted or requested evidence.",
    "DESTINATION_AMBIGUOUS": "Multiple competing destinations or ambiguous observations remain unresolved.",
    "DESTINATION_INCOMPLETE": "Source text contains destination-like instructions not fully accounted for by extraction.",
    "EXTRACTION_FAILED": "Extraction failed; inspect the extraction failure code and original source.",
    "DESTINATION_INVALID": "The destination cannot pass the supported deterministic validation.",
    "UNSUPPORTED_DESTINATION": "The destination scheme or country is outside current support.",
    "DESTINATION_CHANGED": "The full supported destination differs and requires independent checking.",
    "DESTINATION_MATCH": "The full reviewed supported destination matches the selected prior record.",
}


def register_operator_workflow(app: Flask, settings: Settings) -> None:
    app.permanent_session_lifetime = timedelta(minutes=30)
    attempts: dict[str, list[float]] = {}
    lock = Lock()
    # One process-local gate epoch; restarting or rotating configuration expires
    # old sessions. Revocation is immediate on logout, without a new auth service.
    epoch = secrets.token_urlsafe(32)
    active_sessions: dict[str, float] = {}

    def bounded_rate(key: str, limit: int) -> None:
        with lock:
            now = time.monotonic()
            # Single-process conservative burst limits, not a distributed quota.
            for stale in tuple(attempts):
                attempts[stale] = [t for t in attempts[stale] if t > now - 60]
                if not attempts[stale]:
                    del attempts[stale]
            if len(attempts) >= 512 and key not in attempts:
                abort(429)
            recent = attempts.setdefault(key, [])
            if len(recent) >= limit:
                abort(429)
            recent.append(now)

    def store() -> SQLiteStore:
        if "workflow_store" not in g:
            g.workflow_store = SQLiteStore(settings.data_dir / "payproof.sqlite3")
        return g.workflow_store  # type: ignore[no-any-return]

    @app.teardown_appcontext
    def close_store(error: BaseException | None) -> None:
        database = g.pop("workflow_store", None)
        if database is not None:
            database.close()

    @app.before_request
    def protect_operator() -> Response | None:
        if not request.path.startswith("/operator"):
            return None
        if settings.operator_token is None:
            return Response(
                "Operator workflow is not configured. Set PAYPROOF_OPERATOR_TOKEN and PAYPROOF_SECRET_KEY.",
                status=503,
                mimetype="text/plain",
            )
        with lock:
            now = time.monotonic()
            for identifier in tuple(active_sessions):
                if active_sessions[identifier] <= now:
                    del active_sessions[identifier]
            sid = str(session.get("rate_id", ""))
            valid = session.get("gate_epoch") == epoch and sid in active_sessions
            if valid:
                active_sessions[sid] = now + 1800
        if session.get("operator") and not valid:
            session.clear()
        if request.method == "POST":
            if request.endpoint != "operator_login" and not session.get("operator"):
                abort(401)
            csrf = request.form.get("csrf", "")
            if not csrf or not secrets.compare_digest(
                csrf.encode(), session.get("csrf", "").encode()
            ):
                abort(403)
            for header in ("Origin", "Referer"):
                value = request.headers.get(header)
                if value and urlsplit(value)[:2] != urlsplit(request.host_url)[:2]:
                    abort(403)
        if request.endpoint != "operator_login" and not session.get("operator"):
            return redirect(url_for("operator_login"))
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return None

    @app.after_request
    def private_response(response: Response) -> Response:
        if request.path.startswith("/operator"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self'; form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    def safe_error(error: Exception) -> tuple[str, int]:
        if not request.path.startswith("/operator"):
            if isinstance(error, HTTPException):
                return str(error.description), error.code or 500
            return "Request failed.", 500
        code = (
            error.code
            if isinstance(error, HTTPException)
            else 409
            if isinstance(error, WorkflowError)
            else 503
            if isinstance(error, sqlite3.Error)
            else 400
        )
        message = (
            str(error)
            if isinstance(error, WorkflowError)
            else {
                400: "Input was rejected. Check supported text, required fields, dates and full GB/DE IBAN.",
                401: "Operator login is required.",
                403: "Form token or request origin was rejected. Reload the page.",
                413: "Input is too large; nothing was truncated or stored.",
                429: "Too many attempts. Wait one minute before trying again.",
                503: "Storage is unavailable. No successful write is claimed.",
            }.get(code or 500, "Request could not be completed.")
        )
        return render_template("operator_error.html", message=message), code or 500

    for error_type in (ValueError, sqlite3.Error, HTTPException):
        app.register_error_handler(error_type, safe_error)

    def human() -> str:
        return str(session["operator"])

    def fields(allowed: set[str], allowed_files: set[str] | None = None) -> None:
        if set(request.files) - (allowed_files or set()):
            raise ValueError("unexpected file fields")
        if set(request.form) - (allowed | {"csrf"}) or any(
            len(request.form.getlist(k)) != 1 for k in request.form
        ):
            raise ValueError("unexpected form fields")

    def no_secrets(value: object) -> None:
        reject_configured_secrets(value, settings)

    @app.route("/operator/login", methods=["GET", "POST"])
    def operator_login() -> str | Response:
        if request.method == "POST":
            fields({"token", "operator"})
            bounded_rate("login:" + (request.remote_addr or "unknown"), 5)
            token, operator = (
                request.form.get("token", ""),
                request.form.get("operator", "").strip(),
            )
            assert settings.operator_token is not None
            if not secrets.compare_digest(
                token.encode(), settings.operator_token.get_secret_value().encode()
            ):
                abort(401)
            no_secrets(operator)
            if not operator or len(operator) > 256:
                raise ValueError("operator label required")
            with lock:
                active_sessions.pop(str(session.get("rate_id", "")), None)
                if len(active_sessions) >= 512:
                    abort(429)
                sid = secrets.token_urlsafe(32)
                active_sessions[sid] = time.monotonic() + 1800
            session.clear()
            session["operator"] = operator
            session["csrf"] = secrets.token_urlsafe(32)
            session["rate_id"] = sid
            session["gate_epoch"] = epoch
            session.permanent = True
            return redirect(url_for("operator_home"))
        return render_template("operator_login.html")

    @app.post("/operator/logout")
    def operator_logout() -> Response:
        fields(set())
        with lock:
            active_sessions.pop(str(session.get("rate_id", "")), None)
        session.clear()
        return redirect(url_for("operator_login"))

    @app.get("/operator")
    def operator_home() -> str:
        vendors, cases = store().list_vendors(), store().list_cases()
        no_secrets(tuple(v.model_dump(mode="json") for v in vendors))
        no_secrets(tuple(c.model_dump(mode="json") for c in cases))
        return render_template(
            "operator_home.html",
            vendors=vendors,
            cases=cases,
            mode=settings.extraction_mode,
        )

    @app.route("/operator/vendors/new", methods=["GET", "POST"])
    def operator_vendor() -> str | Response:
        if request.method == "GET":
            return render_template("operator_vendor.html")
        fields(
            {
                "name",
                "account",
                "contact_method",
                "contact",
                "source_reference",
                "description",
                "verified_at",
                "trusted_before_request",
            }
        )
        no_secrets(tuple(request.form.values()))
        if request.form.get("trusted_before_request") != "yes":
            raise ValueError("prior trust must be explicitly acknowledged")
        verified_at = datetime.fromisoformat(request.form["verified_at"].replace("Z", "+00:00"))
        if verified_at.tzinfo != UTC or verified_at >= datetime.now(UTC):
            raise ValueError("prior UTC verification required")
        provenance = TrustProvenance(
            source_kind="ONBOARDING_RECORD",
            source_reference=request.form["source_reference"],
            description=request.form["description"],
            recorded_by=human(),
            recorded_at=verified_at,
        )
        raw = request.form["account"]
        vendor = TrustedVendorRecord(
            vendor_id=uuid4(),
            revision_id=uuid4(),
            canonical_vendor_name=request.form["name"],
            payment_identity=NormalizedPaymentIdentity(
                normalization_version="iban-gb-de-v1",
                scheme="IBAN",
                raw_account_identifier=raw,
                account_identifier=canonical_iban(raw),
            ),
            callback_contact=TrustedCallbackContact.model_validate(
                {
                    "contact_id": uuid4(),
                    "revision_id": uuid4(),
                    "method": request.form["contact_method"],
                    "value": request.form["contact"],
                    "provenance": provenance,
                    "last_verified_at": verified_at,
                }
            ),
            provenance=provenance,
            last_verified_at=verified_at,
        )
        store().put_vendor(vendor, operator_id=human())
        return redirect(url_for("operator_home"))

    @app.post("/operator/demo-vendor")
    def operator_demo_vendor() -> Response:
        fields(set())
        from payproof.fixtures import load_corpus

        vendor = next(
            v
            for v in load_corpus().vendors
            if v.canonical_vendor_name == "Synthetic PayProof Demo Supplies"
        )
        store().put_vendor(vendor, operator_id=human())
        return redirect(url_for("operator_home"))

    @app.route("/operator/cases/new", methods=["GET", "POST"])
    def operator_create_case() -> str | Response:
        from payproof.fixtures import load_corpus

        demo = next(r for r in load_corpus().requests if r.fixture_id == "demo-account-change")
        if request.method == "GET":
            vendors = store().list_vendors()
            no_secrets(tuple(v.model_dump(mode="json") for v in vendors))
            return render_template(
                "operator_new_case.html",
                vendors=vendors,
                mode=settings.extraction_mode,
                demo_text=demo.source.text,
                demo_selected=request.args.get("demo") == "1",
                demo_vendor_id=demo.vendor_id,
            )
        fields(
            {"vendor_id", "email", "invoice", "vendor_notice", "plain_text", "upload_kind"},
            {"upload"},
        )
        if set(request.files) - {"upload"}:
            raise ValueError("unsupported upload field")
        bounded_rate("extract:" + str(session["rate_id"]), 6)
        baseline = store().get_vendor(UUID(request.form["vendor_id"]))
        sources: list[SourceDocument] = []
        for name, kind in (
            ("email", "EMAIL"),
            ("invoice", "INVOICE"),
            ("vendor_notice", "VENDOR_NOTICE"),
            ("plain_text", "PLAIN_TEXT"),
        ):
            # Browser form transport uses CRLF. Freeze pasted text with LF before
            # extraction; uploaded file contents remain untouched.
            no_secrets(request.form.get(name, ""))
            text = request.form.get(name, "").replace("\r\n", "\n")
            if text:
                no_secrets(text)
                sources.append(capture_text(text, operator_id=human(), kind=cast(SourceKind, kind)))
        for upload in request.files.getlist("upload"):
            if not upload.filename:
                continue
            if not upload.filename.lower().endswith((".txt", ".eml")):
                raise ValueError("only UTF-8 text upload supported")
            raw = upload.stream.read(80_001)
            if len(raw) > 80_000:
                raise ValueError("upload too large")
            text = raw.decode("utf-8")
            no_secrets(text)
            sources.append(
                capture_text(
                    text,
                    operator_id=human(),
                    kind=cast(SourceKind, request.form.get("upload_kind", "PLAIN_TEXT")),
                )
            )
        # Existing capture and source-bound contracts enforce aggregate bounds too.
        snapshot = start_case(baseline, tuple(sources), settings=settings)
        no_secrets(snapshot.model_dump(mode="json"))
        case = store().create_case(
            CaseInputs(sources=snapshot.sources, evidence=snapshot.evidence),
            baseline.vendor_id,
            operator_id=human(),
            expected_vendor_revision_id=baseline.revision_id,
        )
        return redirect(url_for("operator_case", case_id=case.case_id))

    @app.get("/operator/cases/<uuid:case_id>")
    def operator_case(case_id: UUID) -> str:
        case = store().get_case(case_id)
        history, attempts = store().case_history(case_id), store().verification_events(case_id)
        no_secrets(case.model_dump(mode="json"))
        no_secrets(tuple(c.model_dump(mode="json") for c in history))
        no_secrets(tuple(e.model_dump(mode="json") for e in attempts))
        return render_template(
            "operator_case.html",
            case=case,
            snapshot=case.snapshot,
            inventory=source_inventory(case.snapshot.sources),
            extracted_destination_keys=extracted_keys(case.snapshot.evidence),
            observation_key=observation_key,
            history=history,
            attempts=attempts,
            fields=EVIDENCE_FIELDS,
            reason_explanations=REASON_EXPLANATIONS,
        )

    @app.post("/operator/cases/<uuid:case_id>/<action>")
    def operator_case_action(case_id: UUID, action: str) -> Response:
        allowed = {"revision_id"}
        if action == "review":
            allowed |= {"source_review"}
        if action == "verify":
            allowed |= {
                "action_id",
                "independently_checked",
                "what_was_checked",
                "outcome",
                "person",
                "notes",
            }
        fields(allowed)
        revision = UUID(request.form["revision_id"])
        database = store()
        if action == "review":
            database.review(
                case_id,
                revision,
                operator_id=human(),
                destination_instructions_checked=request.form.get("source_review") == "yes",
            )
        elif action == "compare":
            database.compare(case_id, revision, operator_id=human())
        elif action == "refresh":
            current = database.get_case(case_id)
            database.replace_inputs(
                case_id,
                revision,
                CaseInputs(sources=current.snapshot.sources, evidence=current.snapshot.evidence),
                operator_id=human(),
            )
        elif action == "verify":
            no_secrets(tuple(request.form.values()))
            command = IndependentCheckAction.model_validate(
                {
                    "action_id": UUID(request.form["action_id"]),
                    "operator_id": human(),
                    "independently_checked": request.form.get("independently_checked") == "yes",
                    "what_was_checked": request.form["what_was_checked"],
                    "outcome": request.form["outcome"],
                    "independently_reached_person": request.form.get("person", "").strip() or None,
                    "notes": request.form.get("notes", "").strip() or None,
                }
            )
            database.record_independent_check(case_id, revision, command)
        else:
            abort(404)
        return redirect(url_for("operator_case", case_id=case_id))

    @app.context_processor
    def operator_context() -> dict[str, object]:
        return {"new_action_id": uuid4}
