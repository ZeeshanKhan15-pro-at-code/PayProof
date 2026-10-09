"""Small server-rendered adapter to existing durable workflow commands."""

import json
import secrets
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from hashlib import sha256
from threading import Lock
from typing import cast
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, UUID, uuid4, uuid5

from flask import Flask, abort, g, jsonify, redirect, render_template, request, session, url_for
from werkzeug.exceptions import HTTPException, TooManyRequests
from werkzeug.wrappers import Response

from payproof.baselines import BaselineAssertion, BaselineDraft
from payproof.cases import start_case
from payproof.config import Settings
from payproof.documents import capture_text
from payproof.extraction import extract_documents
from payproof.instruction_safety import extracted_keys, observation_key, source_inventory
from payproof.normalization import canonical_iban
from payproof.schemas import (
    EVIDENCE_FIELDS,
    CaseContract,
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


class SourceInputError(ValueError):
    """Only fixed, user-actionable validation messages, never source contents."""


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


def register_operator_workflow(app: Flask, settings: Settings, *, public: bool = False) -> None:
    prefix = "" if public else "/operator"
    app.permanent_session_lifetime = timedelta(minutes=30)
    attempts: dict[str, list[float]] = {}
    lock = Lock()
    # One process-local gate epoch; restarting or rotating configuration expires
    # old sessions. Revocation is immediate on logout, without a new auth service.
    epoch = secrets.token_urlsafe(32)
    active_sessions: dict[str, float] = {}
    public_writes: dict[str, int] = {}

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
            path = settings.data_dir / "payproof.sqlite3"
            if public:
                sid = str(session.get("rate_id", ""))
                if (
                    not session.get("operator")
                    or len(sid) != 32
                    or any(c not in "0123456789abcdef" for c in sid)
                ):
                    abort(403)
                root = settings.data_dir / "public-sessions"
                if root.is_symlink():
                    raise WorkflowError("public storage must not be a symlink")
                folder = root / sid
                if folder.is_symlink():
                    raise WorkflowError("public storage must not be a symlink")
                folder.mkdir(parents=True, exist_ok=True, mode=0o700)
                folder.touch(exist_ok=True)
                path = folder / "payproof.sqlite3"
            g.workflow_store = SQLiteStore(path)
        return g.workflow_store  # type: ignore[no-any-return]

    @app.teardown_appcontext
    def close_store(error: BaseException | None) -> None:
        database = g.pop("workflow_store", None)
        if database is not None:
            database.close()

    @app.before_request
    def protect_operator() -> Response | None:
        if not public and not request.path.startswith("/operator"):
            return None
        if public and request.endpoint == "static":
            return None
        if settings.environment == "production" and not request.is_secure:
            abort(403)
        if not public and settings.operator_token is None:
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
                    public_writes.pop(identifier, None)
            sid = str(session.get("rate_id", ""))
            valid = session.get("gate_epoch") == epoch and sid in active_sessions
            if valid:
                active_sessions[sid] = now + 1800
        if session.get("operator") and not valid:
            session.clear()
        if public and not valid:
            if request.method != "GET":
                abort(403)
            from payproof.public_workspace import MAX_PUBLIC_SESSIONS, cleanup_sessions

            bounded_rate("public-session:" + (request.remote_addr or "unknown"), 4)
            with lock:
                if len(active_sessions) >= MAX_PUBLIC_SESSIONS:
                    abort(429)
                cleanup_sessions(
                    settings.data_dir / "public-sessions",
                    active_ids=frozenset(active_sessions),
                )
                sid = uuid4().hex
                active_sessions[sid] = time.monotonic() + 1800
                public_writes[sid] = 0
            session.clear()
            session.update(
                operator="anonymous-human",
                csrf=secrets.token_urlsafe(32),
                rate_id=sid,
                gate_epoch=epoch,
            )
            session.permanent = True
        if public and request.method == "GET":
            bounded_rate("public-reads:" + sid, 120)
            bounded_rate("public-reads-ip:" + (request.remote_addr or "unknown"), 240)
            bounded_rate("public-reads-global", 480)
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
            if public and request.endpoint != "operator_logout":
                bounded_rate("public-writes:" + sid, 30)
                bounded_rate("public-writes-ip:" + (request.remote_addr or "unknown"), 60)
                bounded_rate("public-writes-global", 120)
                with lock:
                    if public_writes.get(sid, 0) >= 128:
                        raise TooManyRequests(
                            description="This temporary workspace's write allowance is exhausted. Read-only history and ending the workspace remain available."
                        )
                    public_writes[sid] = public_writes.get(sid, 0) + 1
        if request.endpoint != "operator_login" and not session.get("operator"):
            return redirect(url_for("operator_login"))
        if "csrf" not in session:
            session["csrf"] = secrets.token_urlsafe(32)
        return None

    @app.after_request
    def private_response(response: Response) -> Response:
        if public or request.path.startswith("/operator"):
            response.headers["Cache-Control"] = "no-store"
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "same-origin"
            script_policy = (
                "script-src 'self'; " if request.endpoint == "verification_receipt" else ""
            )
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self'; "
                + script_policy
                + "form-action 'self'; frame-ancestors 'none'; base-uri 'none'"
            )
        return response

    def safe_error(error: Exception) -> tuple[str, int]:
        if not public and not request.path.startswith("/operator"):
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
        if isinstance(error, SourceInputError):
            message = str(error)
        if code == 403 and settings.environment == "production" and not request.is_secure:
            message = "HTTPS is required. Use the HTTPS site; the host must configure a trusted TLS proxy before serving this workflow."
        if public and isinstance(error, TooManyRequests):
            message = error.description
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

    def before_extraction(operation_id: UUID) -> None:
        if public and settings.extraction_mode == "live":
            from payproof.public_workspace import PublicLiveCallDenied, reserve_live_call

            bounded_rate("public-extract:" + (request.remote_addr or "unknown"), 3)
            try:
                reserve_live_call(
                    settings,
                    operation_id=uuid5(
                        NAMESPACE_URL,
                        "public-live:" + str(session["rate_id"]) + ":" + str(operation_id),
                    ),
                )
            except PublicLiveCallDenied as error:
                if error.reason == "DUPLICATE_OPERATION":
                    raise TooManyRequests(
                        description="An extraction for this submission or revision has already been reserved. No second provider request was made. Reload the case or original submission result."
                    ) from None
                raise TooManyRequests(
                    description="Public live request allowance is exhausted. No provider request was made; the owner must replenish the configured allowance."
                ) from None

    def read_sources(*, required: bool = False) -> tuple[SourceDocument, ...]:
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
                raise SourceInputError(
                    "Only UTF8 .txt and raw .eml text files are supported. PDF, MSG, MIME attachments and OCR are not parsed."
                )
            raw = upload.stream.read(80_001)
            if len(raw) > 80_000:
                raise SourceInputError(
                    "Each upload must be at most 80,000 bytes; reduce the file size. Nothing was truncated."
                )
            try:
                text = raw.decode("utf-8")
            except UnicodeError:
                raise SourceInputError(
                    "The upload is not valid UTF8 text. Export a UTF8 .txt file and try again."
                ) from None
            no_secrets(text)
            sources.append(
                capture_text(
                    text,
                    operator_id=human(),
                    kind=cast(SourceKind, request.form.get("upload_kind", "PLAIN_TEXT")),
                )
            )
        if required and not sources:
            raise SourceInputError(
                "Paste the current request text or choose a supported UTF8 .txt/.eml upload."
            )
        return tuple(sources)

    @app.route((prefix + "/login" or "/"), methods=["GET", "POST"])
    def operator_login() -> str | Response:
        if public:
            abort(404)
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
                old_sid = str(session.get("rate_id", ""))
                active_sessions.pop(old_sid, None)
                public_writes.pop(old_sid, None)
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

    @app.post(prefix + "/logout" or "/")
    def operator_logout() -> Response:
        fields(set())
        with lock:
            old_sid = str(session.get("rate_id", ""))
            active_sessions.pop(old_sid, None)
            public_writes.pop(old_sid, None)
        session.clear()
        return redirect(url_for("operator_home" if public else "operator_login"))

    @app.get(prefix + "" or "/")
    def operator_home() -> str:
        vendors, cases = store().list_vendors(), store().list_cases()
        no_secrets(tuple(v.model_dump(mode="json") for v in vendors))
        no_secrets(tuple(c.model_dump(mode="json") for c in cases))
        return render_template(
            "operator_home.html",
            vendors=vendors,
            cases=cases,
            mode=settings.extraction_mode,
            public=public,
        )

    @app.route((prefix + "/vendors/new" or "/"), methods=["GET", "POST"])
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
        key = json.dumps(dict(request.form) | {"operator": human(), "csrf": ""}, sort_keys=True)
        identity = uuid5(NAMESPACE_URL, "manual-baseline:" + key)
        vendor = TrustedVendorRecord(
            vendor_id=identity,
            revision_id=uuid5(identity, "revision"),
            canonical_vendor_name=request.form["name"],
            payment_identity=NormalizedPaymentIdentity(
                normalization_version="iban-gb-de-v1",
                scheme="IBAN",
                raw_account_identifier=raw,
                account_identifier=canonical_iban(raw),
            ),
            callback_contact=TrustedCallbackContact.model_validate(
                {
                    "contact_id": uuid5(identity, "contact"),
                    "revision_id": uuid5(identity, "contact-revision"),
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

    @app.route((prefix + "/baselines/new" or "/"), methods=["GET", "POST"])
    def baseline_new() -> str | Response:
        vendor = (
            store().get_vendor(UUID(request.args["vendor_id"]))
            if request.args.get("vendor_id")
            else None
        )
        if request.method == "GET":
            return render_template("baseline_new.html", vendor=vendor)
        fields(
            {
                "name",
                "source_reference",
                "description",
                "verified_at",
                "account",
                "email",
                "invoice",
                "vendor_notice",
                "plain_text",
                "upload_kind",
                "submission_id",
                "expected_revision_id",
                "bank_name",
                "trusted_email",
                "trusted_domain",
                "currency",
            },
            {"upload"},
        )
        no_secrets(tuple(request.form.values()))
        if vendor and request.form.get("expected_revision_id") != str(vendor.revision_id):
            raise WorkflowError("trusted vendor changed; reload revision form")
        sources = read_sources()
        if sources and request.form.get("account", "").strip():
            raise SourceInputError(
                "Choose manual full destination OR previous source evidence, not both. The draft will be reviewed before trust is asserted."
            )
        values = {k: v for k, v in request.form.items() if k not in {"csrf", "submission_id"}}
        digest = sha256(
            json.dumps(
                {
                    "form": values,
                    "sources": [(s.kind, s.text) for s in sources],
                    "operator": human(),
                    "vendor": str(vendor.vendor_id) if vendor else None,
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        draft_id = uuid5(
            NAMESPACE_URL,
            "baseline:" + str(request.form.get("submission_id") or digest) + ":" + human(),
        )
        existing = (
            store()
            .db.execute("SELECT payload FROM baseline_drafts WHERE draft_id=?", (str(draft_id),))
            .fetchone()
        )
        if existing:
            old = store().get_baseline_draft(draft_id)
            if old.submission_digest != digest:
                raise WorkflowError("baseline submission identifier reused")
            return redirect(url_for("baseline_draft", draft_id=draft_id))
        inputs = None
        if sources:
            bounded_rate("extract:" + str(session["rate_id"]), 6)
            before_extraction(draft_id)
            evidence = extract_documents(sources, settings=settings)
            inputs = CaseInputs(sources=sources, evidence=evidence)
        draft = BaselineDraft(
            draft_id=draft_id,
            vendor_id=vendor.vendor_id if vendor else uuid4(),
            expected_vendor_revision_id=vendor.revision_id if vendor else None,
            operator_id=human(),
            created_at=datetime.now(UTC),
            submission_digest=digest,
            name=request.form["name"],
            bank_name=request.form.get("bank_name", "").strip() or None,
            trusted_email=request.form.get("trusted_email", "").strip() or None,
            trusted_domain=request.form.get("trusted_domain", "").strip() or None,
            currency=request.form.get("currency", "").strip() or None,
            source_reference=request.form["source_reference"],
            description=request.form["description"],
            prior_verified_at=datetime.fromisoformat(
                request.form["verified_at"].replace("Z", "+00:00")
            ),
            manual_account=request.form.get("account", "").strip() or None,
            inputs=inputs,
        )
        no_secrets(draft.model_dump(mode="json"))
        store().save_baseline_draft(draft)
        return redirect(url_for("baseline_draft", draft_id=draft.draft_id))

    @app.route((prefix + "/baselines/<uuid:draft_id>" or "/"), methods=["GET", "POST"])
    def baseline_draft(draft_id: UUID) -> str | Response:
        draft = store().get_baseline_draft(draft_id)
        no_secrets(draft.model_dump(mode="json"))
        if request.method == "POST":
            fields(
                {
                    "source_reviewed",
                    "previously_trusted",
                    "contact_independently_established",
                    "contact_method",
                    "contact",
                }
            )
            no_secrets(tuple(request.form.values()))
            action = BaselineAssertion.model_validate(
                {
                    "draft_id": draft_id,
                    "operator_id": human(),
                    "source_reviewed": request.form.get("source_reviewed") == "yes",
                    "previously_trusted": request.form.get("previously_trusted") == "yes",
                    "contact_independently_established": request.form.get(
                        "contact_independently_established"
                    )
                    == "yes",
                    "contact_method": request.form["contact_method"],
                    "contact_value": request.form["contact"],
                }
            )
            record = store().assert_baseline(action)
            return redirect(
                url_for("operator_create_case", vendor_id=record.vendor_id)
                if public
                else url_for("operator_home")
            )
        try:
            destination = draft.identity().account_identifier
            issue = None
        except ValueError:
            destination, issue = (
                None,
                "Baseline destination is unresolved; no trust assertion can be recorded. Inspect all sources or create a corrected draft.",
            )
        return render_template(
            "baseline_draft.html", draft=draft, destination=destination, issue=issue
        )

    @app.get(prefix + "/cases/<uuid:case_id>/receipts/<uuid:event_id>" or "/")
    def verification_receipt(case_id: UUID, event_id: UUID) -> str | Response:
        receipt = store().verification_receipt(case_id, event_id)
        no_secrets(receipt)
        if request.accept_mimetypes.best == "text/html":
            recorded = CaseContract.model_validate_json(json.dumps(receipt["snapshot"]))
            return render_template(
                "verification_receipt.html",
                receipt=receipt,
                case_id=case_id,
                reason_explanations=REASON_EXPLANATIONS,
                inventory=source_inventory(recorded.sources),
                extracted_destination_keys=extracted_keys(recorded.evidence),
                observation_key=observation_key,
                **(
                    {"extraction_label": "SYNTHETIC DEMONSTRATION · replayed observations"}
                    if recorded.evidence.extraction.method == "FIXTURE"
                    else {}
                ),
            )
        return jsonify(receipt)

    @app.post(prefix + "/demo-vendor" or "/")
    def operator_demo_vendor() -> Response:
        if public:
            abort(404)
        fields(set())
        from payproof.fixtures import load_corpus

        vendor = next(
            v
            for v in load_corpus().vendors
            if v.canonical_vendor_name == "Synthetic PayProof Demo Supplies"
        )
        store().put_vendor(vendor, operator_id=human())
        return redirect(url_for("operator_home"))

    @app.route((prefix + "/cases/new" or "/"), methods=["GET", "POST"])
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
                selected_vendor_id=request.args.get("vendor_id"),
            )
        fields(
            {
                "vendor_id",
                "email",
                "invoice",
                "vendor_notice",
                "plain_text",
                "upload_kind",
                "submission_id",
            },
            {"upload"},
        )
        if set(request.files) - {"upload"}:
            raise ValueError("unsupported upload field")
        bounded_rate("extract:" + str(session["rate_id"]), 6)
        baseline = store().get_vendor(UUID(request.form["vendor_id"]))
        sources = read_sources(required=True)
        digest = sha256(
            json.dumps(
                {
                    "operator": human(),
                    "vendor": str(baseline.vendor_id),
                    "sources": [(s.kind, s.text) for s in sources],
                },
                sort_keys=True,
            ).encode()
        ).hexdigest()
        submission = uuid5(
            NAMESPACE_URL,
            "case:" + str(request.form.get("submission_id") or digest) + ":" + human(),
        )
        previous = store().submission(submission, "CASE", digest)
        if previous is not None:
            return redirect(url_for("operator_case", case_id=previous))
        # Existing capture and source-bound contracts enforce aggregate bounds too.
        before_extraction(submission)
        snapshot = start_case(baseline, tuple(sources), settings=settings)
        no_secrets(snapshot.model_dump(mode="json"))
        case = store().create_case(
            CaseInputs(sources=snapshot.sources, evidence=snapshot.evidence),
            baseline.vendor_id,
            operator_id=human(),
            expected_vendor_revision_id=baseline.revision_id,
            submission_id=submission,
            submission_digest=digest,
        )
        return redirect(url_for("operator_case", case_id=case.case_id))

    @app.route((prefix + "/cases/<uuid:case_id>/sources" or "/"), methods=["GET", "POST"])
    def operator_replace_sources(case_id: UUID) -> str | Response:
        current = store().get_case(case_id)
        baseline = store().get_vendor(current.selected_vendor_id)
        if request.method == "GET":
            no_secrets(current.model_dump(mode="json"))
            return render_template(
                "operator_new_case.html",
                editing=current,
                vendors=(baseline,),
                mode=settings.extraction_mode,
                demo_text="",
                demo_selected=False,
            )
        fields(
            {"revision_id", "email", "invoice", "vendor_notice", "plain_text", "upload_kind"},
            {"upload"},
        )
        revision = UUID(request.form["revision_id"])
        if current.revision_id != revision:
            raise WorkflowError("stale case: reload the source form")
        bounded_rate("extract:" + str(session["rate_id"]), 6)
        sources = read_sources(required=True)
        before_extraction(uuid5(case_id, "revision-extraction:" + str(revision)))
        evidence = extract_documents(sources, settings=settings, request_id=case_id)
        inputs = CaseInputs(sources=sources, evidence=evidence)
        no_secrets(inputs.model_dump(mode="json"))
        store().replace_inputs(
            case_id,
            revision,
            inputs,
            operator_id=human(),
            expected_vendor_revision_id=baseline.revision_id,
        )
        return redirect(url_for("operator_case", case_id=case_id))

    @app.get(prefix + "/cases/<uuid:case_id>" or "/")
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
            **(
                {"extraction_label": "SYNTHETIC DEMONSTRATION · replayed observations"}
                if case.snapshot.evidence.extraction.method == "FIXTURE"
                else {}
            ),
        )

    @app.post(prefix + "/cases/<uuid:case_id>/<action>" or "/")
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
        elif action == "extract":
            current = database.get_case(case_id)
            if current.revision_id != revision:
                raise WorkflowError("stale case: refresh before retry")
            baseline = database.get_vendor(current.selected_vendor_id)
            bounded_rate("extract:" + str(session["rate_id"]), 6)
            sources = tuple(
                capture_text(s.text, kind=s.kind, operator_id=human())
                for s in current.snapshot.sources
            )
            before_extraction(uuid5(case_id, "revision-extraction:" + str(revision)))
            evidence = extract_documents(sources, settings=settings, request_id=case_id)
            inputs = CaseInputs(sources=sources, evidence=evidence)
            no_secrets(inputs.model_dump(mode="json"))
            database.replace_inputs(
                case_id,
                revision,
                inputs,
                operator_id=human(),
                expected_vendor_revision_id=baseline.revision_id,
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

    @app.get(prefix + "/examples")
    def public_examples() -> str:
        from payproof.demo_examples import load_examples

        return render_template(
            "public_examples.html",
            catalog=load_examples(),
            extraction_label="SYNTHETIC DEMONSTRATION · replayed observations",
        )

    @app.route(prefix + "/example", defaults={"example_id": "changed"}, methods=["GET", "POST"])
    @app.route(prefix + "/examples/<example_id>", methods=["GET", "POST"])
    def public_example(example_id: str) -> str | Response:
        from payproof.demo_examples import instantiate_example, load_examples

        catalog = load_examples()
        item = next((c for c in catalog.cases if c.case_id == example_id), None)
        if item is None:
            abort(404)
        if request.method == "POST":
            fields({"submission_id"})
            submission = uuid5(
                NAMESPACE_URL,
                "public-example:"
                + str(
                    UUID(request.form["submission_id"])
                    if request.form.get("submission_id")
                    else example_id
                )
                + ":"
                + human(),
            )
            digest = sha256((catalog.model_dump_json() + ":" + example_id).encode()).hexdigest()
            database = store()
            previous = database.submission(submission, "CASE", digest)
            if previous is not None:
                return redirect(url_for("operator_case", case_id=previous))
            bounded_rate("examples:" + str(session["rate_id"]), 12)
            baseline, inputs = instantiate_example(catalog, item, submission)
            no_secrets(inputs.model_dump(mode="json"))
            database.put_vendor(baseline, operator_id=human())
            case = database.create_case(
                inputs,
                baseline.vendor_id,
                operator_id=human(),
                expected_vendor_revision_id=baseline.revision_id,
                submission_id=submission,
                submission_digest=digest,
            )
            return redirect(url_for("operator_case", case_id=case.case_id))
        return render_template(
            "public_example.html",
            catalog=catalog,
            item=item,
            extraction_label="SYNTHETIC DEMONSTRATION · replayed observations",
        )

    @app.context_processor
    def operator_context() -> dict[str, object]:
        return {
            "new_action_id": uuid4,
            "public_workspace": public,
            "extraction_label": "LIVE EXTRACTION"
            if settings.extraction_mode == "live"
            else "DEMO EXAMPLE"
            if settings.extraction_mode == "fixture"
            else "LIVE EXTRACTION DISABLED",
        }
