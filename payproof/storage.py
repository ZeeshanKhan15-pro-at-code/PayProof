"""Private SQLite workflow: immutable snapshots, atomic revision checks and audit events."""

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime
from hashlib import sha256
from importlib.resources import files
from pathlib import Path
from uuid import UUID, uuid4

from payproof.baselines import BaselineAssertion, BaselineDraft, trusted_record
from payproof.cases import complete_case, review_case
from payproof.schemas import CaseContract, HumanVerificationRecord, TrustedVendorRecord
from payproof.workflow_contracts import (
    CaseInputs,
    IndependentCheckAction,
    IndependentCheckEvent,
    StoredCase,
)


class WorkflowError(ValueError):
    """Safe workflow rejection; never includes source text or credentials."""


def engine_fingerprint() -> str:
    return sha256(
        b"".join(
            files("payproof").joinpath(name).read_bytes()
            for name in ("comparison.py", "normalization.py", "schemas.py", "instruction_safety.py")
        )
    ).hexdigest()


class SQLiteStore:
    def __init__(self, path: Path):
        if path.is_symlink():
            raise WorkflowError("database must not be a symlink")
        path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.db = sqlite3.connect(path, isolation_level=None, timeout=5)
        path.chmod(0o600)
        self.db.row_factory = sqlite3.Row
        self.db.execute("PRAGMA foreign_keys=ON")
        version = self.db.execute("PRAGMA user_version").fetchone()[0]
        if version == 0:
            if self.db.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchone():
                self.close()
                raise WorkflowError("unversioned database is not empty")
            self.db.executescript(
                files("payproof").joinpath("migrations/001_initial.sql").read_text()
            )
        elif version not in (1, 2):
            self.close()
            raise WorkflowError("unsupported database version")
        required = {
            "schema_migrations",
            "trusted_contacts",
            "vendor_revisions",
            "vendor_heads",
            "sources",
            "extraction_attempts",
            "case_revisions",
            "case_heads",
            "workflow_events",
            "verification_attempts",
            "human_confirmations",
        }
        tables = {
            row[0] for row in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not required.issubset(tables):
            self.close()
            raise WorkflowError("incomplete database schema")
        if tuple(
            row[0]
            for row in self.db.execute("SELECT version FROM schema_migrations ORDER BY version")
        ) != ((1, 2) if version == 2 else (1,)):
            self.close()
            raise WorkflowError("invalid migration ledger")
        if version in (0, 1):
            self.db.executescript(
                files("payproof").joinpath("migrations/002_baseline_workflow.sql").read_text()
            )
        extra = {"baseline_drafts", "baseline_assertions", "workflow_submissions"}
        tables = {
            r[0] for r in self.db.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        if not extra.issubset(tables):
            self.close()
            raise WorkflowError("incomplete database schema")
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.execute("PRAGMA synchronous=FULL")

    def close(self) -> None:
        self.db.close()

    @contextmanager
    def _transaction(self) -> Iterator[None]:
        self.db.execute("BEGIN IMMEDIATE")
        try:
            yield
            self.db.execute("COMMIT")
        except BaseException:
            self.db.execute("ROLLBACK")
            raise

    def _bind(self, table: str, column: str, identifier: str, payload: str) -> None:
        # Identifiers are internal constants, never user input.
        row = self.db.execute(
            f"SELECT payload FROM {table} WHERE {column}=?", (identifier,)
        ).fetchone()
        if row:
            if row["payload"] != payload:
                raise WorkflowError("immutable identifier reused with different data")
        else:
            self.db.execute(
                f"INSERT INTO {table}({column},payload) VALUES (?,?)", (identifier, payload)
            )

    def get_vendor(self, vendor_id: UUID) -> TrustedVendorRecord:
        row = self.db.execute(
            "SELECT payload FROM vendor_revisions JOIN vendor_heads USING(vendor_id,revision_id) WHERE vendor_id=?",
            (str(vendor_id),),
        ).fetchone()
        if not row:
            raise WorkflowError("trusted vendor not found")
        return TrustedVendorRecord.model_validate_json(row["payload"])

    def put_vendor(
        self,
        record: TrustedVendorRecord,
        *,
        operator_id: str,
        expected_revision_id: UUID | None = None,
    ) -> None:
        record = TrustedVendorRecord.model_validate(record.model_dump())
        if not operator_id.strip():
            raise WorkflowError("operator required")
        with self._transaction():
            self._put_vendor(record, operator_id, expected_revision_id)

    def _put_vendor(
        self, record: TrustedVendorRecord, operator_id: str, expected_revision_id: UUID | None
    ) -> None:
        head = self.db.execute(
            "SELECT revision_id FROM vendor_heads WHERE vendor_id=?", (str(record.vendor_id),)
        ).fetchone()
        existing = self.db.execute(
            "SELECT payload FROM vendor_revisions WHERE revision_id=?",
            (str(record.revision_id),),
        ).fetchone()
        if existing:
            if (
                head
                and head[0] == str(record.revision_id)
                and existing[0] == record.model_dump_json()
            ):
                return
            raise WorkflowError("vendor revision is immutable and cannot be restored")
        if not head and expected_revision_id is not None:
            raise WorkflowError("trusted vendor revision no longer exists")
        if head and head[0] != str(expected_revision_id):
            raise WorkflowError("stale vendor revision")
        contact = record.callback_contact
        prior = self.db.execute(
            "SELECT payload FROM trusted_contacts WHERE contact_id=? AND revision_id=?",
            (str(contact.contact_id), str(contact.revision_id)),
        ).fetchone()
        if prior and prior[0] != contact.model_dump_json():
            raise WorkflowError("contact revision is immutable")
        if not prior:
            self.db.execute(
                "INSERT INTO trusted_contacts VALUES (?,?,?)",
                (str(contact.contact_id), str(contact.revision_id), contact.model_dump_json()),
            )
        now = datetime.now(UTC).isoformat()
        self.db.execute(
            "INSERT INTO vendor_revisions VALUES (?,?,?,?,?)",
            (
                str(record.vendor_id),
                str(record.revision_id),
                record.model_dump_json(),
                now,
                operator_id,
            ),
        )
        self.db.execute(
            "INSERT INTO vendor_heads VALUES (?,?) ON CONFLICT(vendor_id) DO UPDATE SET revision_id=excluded.revision_id",
            (str(record.vendor_id), str(record.revision_id)),
        )
        self.db.execute(
            "INSERT INTO workflow_events VALUES (?,NULL,NULL,?,?,?,?)",
            (str(uuid4()), "VENDOR_RECORDED", operator_id, now, record.model_dump_json()),
        )

    def get_case(self, case_id: UUID, revision_id: UUID | None = None) -> StoredCase:
        head = self.db.execute(
            "SELECT revision_id FROM case_heads WHERE case_id=?", (str(case_id),)
        ).fetchone()
        if not head:
            raise WorkflowError("case not found")
        row = self.db.execute(
            "SELECT * FROM case_revisions WHERE case_id=? AND revision_id=?",
            (str(case_id), str(revision_id) if revision_id else head[0]),
        ).fetchone()
        if not row or sha256(row["payload"].encode()).hexdigest() != row["payload_sha256"]:
            raise WorkflowError("case snapshot missing or corrupt")
        snapshot = CaseContract.model_validate_json(row["payload"])
        if (
            str(snapshot.evidence.request_id) != row["case_id"]
            or (str(snapshot.baseline.revision_id) if snapshot.baseline else None)
            != row["vendor_revision_id"]
        ):
            raise WorkflowError("case binding is corrupt")
        vendor_head = self.db.execute(
            "SELECT revision_id FROM vendor_heads WHERE vendor_id=?", (row["vendor_id"],)
        ).fetchone()
        return StoredCase(
            case_id=case_id,
            revision_id=UUID(row["revision_id"]),
            version=row["version"],
            selected_vendor_id=UUID(row["vendor_id"]),
            recorded_at=datetime.fromisoformat(row["recorded_at"]),
            snapshot=snapshot,
            current_case_revision_id=UUID(head[0]),
            current_vendor_revision_id=UUID(vendor_head[0]) if vendor_head else None,
            engine_fingerprint=row["engine_fingerprint"],
            current_engine_fingerprint=engine_fingerprint(),
        )

    def _current(
        self, case_id: UUID, revision_id: UUID, *, allow_stale: bool = False
    ) -> StoredCase:
        case = self.get_case(case_id)
        if case.revision_id != revision_id or (case.stale and not allow_stale):
            raise WorkflowError("stale case: refresh, review and compare again")
        return case

    def _append(
        self,
        snapshot: CaseContract,
        vendor_id: UUID,
        operator: str,
        kind: str,
        version: int,
        fingerprint: str | None = None,
        event_id: UUID | None = None,
    ) -> StoredCase:
        snapshot = CaseContract.model_validate(snapshot.model_dump())
        if not operator.strip():
            raise WorkflowError("operator required")
        for source in snapshot.sources:
            self._bind("sources", "source_id", str(source.source_id), source.model_dump_json())
        attempt = snapshot.evidence.extraction.attempt_id
        prior = self.db.execute(
            "SELECT payload FROM extraction_attempts WHERE attempt_id=?", (str(attempt),)
        ).fetchone()
        payload = snapshot.evidence.model_dump_json()
        if prior and prior[0] != payload:
            raise WorkflowError("extraction attempt is immutable")
        if not prior:
            self.db.execute(
                "INSERT INTO extraction_attempts VALUES (?,?,?)",
                (str(attempt), str(snapshot.evidence.request_id), payload),
            )
        case_id, revision, now = snapshot.evidence.request_id, uuid4(), datetime.now(UTC)
        payload = snapshot.model_dump_json()
        self.db.execute(
            "INSERT INTO case_revisions VALUES (?,?,?,?,?,?,?,?,?)",
            (
                str(case_id),
                str(revision),
                version,
                str(vendor_id),
                str(snapshot.baseline.revision_id) if snapshot.baseline else None,
                payload,
                sha256(payload.encode()).hexdigest(),
                now.isoformat(),
                fingerprint,
            ),
        )
        self.db.execute(
            "INSERT INTO case_heads VALUES (?,?) ON CONFLICT(case_id) DO UPDATE SET revision_id=excluded.revision_id",
            (str(case_id), str(revision)),
        )
        self.db.execute(
            "INSERT INTO workflow_events VALUES (?,?,?,?,?,?,?)",
            (
                str(event_id or uuid4()),
                str(case_id),
                str(revision),
                kind,
                operator,
                now.isoformat(),
                payload,
            ),
        )
        return self.get_case(case_id)

    def create_case(
        self,
        inputs: CaseInputs,
        vendor_id: UUID,
        *,
        operator_id: str,
        expected_vendor_revision_id: UUID | None = None,
        submission_id: UUID | None = None,
        submission_digest: str | None = None,
    ) -> StoredCase:
        inputs = CaseInputs.model_validate(inputs.model_dump())
        with self._transaction():
            if submission_id is not None:
                if not submission_digest:
                    raise WorkflowError("submission digest required")
                previous = self.submission(submission_id, "CASE", submission_digest)
                if previous is not None:
                    return self.get_case(previous)
            if self.db.execute(
                "SELECT 1 FROM case_heads WHERE case_id=?", (str(inputs.evidence.request_id),)
            ).fetchone():
                raise WorkflowError("case already exists")
            baseline = self.get_vendor(vendor_id)
            if (
                expected_vendor_revision_id is not None
                and baseline.revision_id != expected_vendor_revision_id
            ):
                raise WorkflowError("trusted vendor changed during extraction")
            saved = self._append(
                CaseContract(**inputs.model_dump(), baseline=baseline),
                vendor_id,
                operator_id,
                "CASE_CREATED",
                1,
            )
            if submission_id is not None:
                self.db.execute(
                    "INSERT INTO workflow_submissions VALUES (?,?,?,?)",
                    (str(submission_id), "CASE", submission_digest, str(saved.case_id)),
                )
            return saved

    def replace_inputs(
        self,
        case_id: UUID,
        revision_id: UUID,
        inputs: CaseInputs,
        *,
        operator_id: str,
        expected_vendor_revision_id: UUID | None = None,
    ) -> StoredCase:
        inputs = CaseInputs.model_validate(inputs.model_dump())
        with self._transaction():
            current = self._current(case_id, revision_id, allow_stale=True)
            if inputs.evidence.request_id != case_id:
                raise WorkflowError("request identifier must remain unchanged")
            baseline = self.get_vendor(current.selected_vendor_id)
            if (
                expected_vendor_revision_id is not None
                and baseline.revision_id != expected_vendor_revision_id
            ):
                raise WorkflowError("trusted vendor changed during extraction")
            return self._append(
                CaseContract(**inputs.model_dump(), baseline=baseline),
                current.selected_vendor_id,
                operator_id,
                "INPUT_REPLACED",
                current.version + 1,
            )

    def review(
        self,
        case_id: UUID,
        revision_id: UUID,
        *,
        operator_id: str,
        destination_instructions_checked: bool,
    ) -> StoredCase:
        with self._transaction():
            current = self._current(case_id, revision_id)
            old = current.snapshot
            snapshot = review_case(
                CaseContract(sources=old.sources, evidence=old.evidence, baseline=old.baseline),
                operator_id=operator_id,
                destination_instructions_checked=destination_instructions_checked,
            )
            return self._append(
                snapshot,
                current.selected_vendor_id,
                operator_id,
                "SOURCE_REVIEWED",
                current.version + 1,
            )

    def compare(self, case_id: UUID, revision_id: UUID, *, operator_id: str) -> StoredCase:
        with self._transaction():
            current = self._current(case_id, revision_id)
            old = current.snapshot
            snapshot = complete_case(
                CaseContract(
                    sources=old.sources,
                    evidence=old.evidence,
                    baseline=old.baseline,
                    review=old.review,
                )
            )
            return self._append(
                snapshot,
                current.selected_vendor_id,
                operator_id,
                "COMPARED",
                current.version + 1,
                engine_fingerprint(),
            )

    def record_independent_check(
        self, case_id: UUID, revision_id: UUID, action: IndependentCheckAction
    ) -> IndependentCheckEvent:
        action = IndependentCheckAction.model_validate(action.model_dump())
        digest = sha256(action.model_dump_json().encode()).hexdigest()
        with self._transaction():
            retry = self.db.execute(
                "SELECT * FROM verification_attempts WHERE action_id=?", (str(action.action_id),)
            ).fetchone()
            if retry:
                if (
                    retry["action_sha256"] != digest
                    or retry["case_id"] != str(case_id)
                    or retry["source_revision_id"] != str(revision_id)
                ):
                    raise WorkflowError("action identifier reused")
                self._current(case_id, UUID(retry["resulting_revision_id"]))
                return IndependentCheckEvent.model_validate_json(retry["payload"])
            current = self._current(case_id, revision_id)
            case = current.snapshot
            result, baseline = case.comparison, case.baseline
            if (
                not case.review
                or not result
                or result.state == "UNCERTAIN"
                or not baseline
                or not result.requested_identity
                or current.engine_fingerprint != engine_fingerprint()
            ):
                raise WorkflowError(
                    "independent check requires a current reviewed decisive comparison"
                )
            if case.verification:
                raise WorkflowError("comparison already confirmed")
            contact, now, event_id = baseline.callback_contact, datetime.now(UTC), uuid4()
            confirmation = None
            if action.outcome == "CONFIRMED":
                assert action.independently_reached_person is not None
                confirmation = HumanVerificationRecord(
                    verification_id=uuid4(),
                    comparison_id=result.comparison_id,
                    vendor_id=baseline.vendor_id,
                    baseline_revision_id=baseline.revision_id,
                    trusted_contact_id=contact.contact_id,
                    trusted_contact_revision_id=contact.revision_id,
                    callback_method=contact.method,
                    trusted_callback_value=contact.value,
                    trusted_source=contact.provenance,
                    checked_identity=result.requested_identity,
                    what_was_checked=action.what_was_checked,
                    independently_reached_person=action.independently_reached_person,
                    operator_id=action.operator_id,
                    human_confirmed=True,
                    confirmed_at=now,
                    notes=action.notes,
                )
            event = IndependentCheckEvent(
                event_id=event_id,
                action_id=action.action_id,
                case_id=case_id,
                source_revision_id=revision_id,
                comparison_id=result.comparison_id,
                baseline_revision_id=baseline.revision_id,
                trusted_contact=contact,
                checked_identity=result.requested_identity,
                what_was_checked=action.what_was_checked,
                outcome=action.outcome,
                independently_reached_person=action.independently_reached_person,
                operator_id=action.operator_id,
                independently_checked=True,
                recorded_at=now,
                notes=action.notes,
                confirmation=confirmation,
            )
            snapshot = CaseContract(**(case.model_dump() | {"verification": confirmation}))
            saved = self._append(
                snapshot,
                current.selected_vendor_id,
                action.operator_id,
                "INDEPENDENT_CHECK",
                current.version + 1,
                current.engine_fingerprint,
                event_id,
            )
            self.db.execute(
                "INSERT INTO verification_attempts VALUES (?,?,?,?,?,?,?,?)",
                (
                    str(event_id),
                    str(action.action_id),
                    str(case_id),
                    str(revision_id),
                    str(saved.revision_id),
                    str(result.comparison_id),
                    digest,
                    event.model_dump_json(),
                ),
            )
            if confirmation:
                self.db.execute(
                    "INSERT INTO human_confirmations VALUES (?,?,?,?)",
                    (
                        str(result.comparison_id),
                        str(confirmation.verification_id),
                        str(event_id),
                        confirmation.model_dump_json(),
                    ),
                )
            return event

    def verification_events(self, case_id: UUID) -> tuple[IndependentCheckEvent, ...]:
        return tuple(
            IndependentCheckEvent.model_validate_json(row[0])
            for row in self.db.execute(
                "SELECT payload FROM verification_attempts WHERE case_id=? ORDER BY rowid",
                (str(case_id),),
            )
        )

    def list_vendors(self) -> tuple[TrustedVendorRecord, ...]:
        return tuple(
            self.get_vendor(UUID(row[0]))
            for row in self.db.execute("SELECT vendor_id FROM vendor_heads ORDER BY vendor_id")
        )

    def list_cases(self) -> tuple[StoredCase, ...]:
        return tuple(
            self.get_case(UUID(row[0]))
            for row in self.db.execute(
                "SELECT case_id FROM case_heads ORDER BY rowid DESC LIMIT 50"
            )
        )

    def case_history(self, case_id: UUID) -> tuple[StoredCase, ...]:
        return tuple(
            self.get_case(case_id, UUID(row[0]))
            for row in self.db.execute(
                "SELECT revision_id FROM case_revisions WHERE case_id=? ORDER BY version",
                (str(case_id),),
            )
        )

    def submission(self, submission_id: UUID, kind: str, digest: str) -> UUID | None:
        row = self.db.execute(
            "SELECT * FROM workflow_submissions WHERE submission_id=?", (str(submission_id),)
        ).fetchone()
        if row is None:
            return None
        if row["kind"] != kind or row["digest"] != digest:
            raise WorkflowError("submission identifier reused with different data")
        return UUID(row["result_id"])

    def save_baseline_draft(self, draft: BaselineDraft) -> BaselineDraft:
        draft = BaselineDraft.model_validate(draft.model_dump())
        with self._transaction():
            row = self.db.execute(
                "SELECT payload FROM baseline_drafts WHERE draft_id=?", (str(draft.draft_id),)
            ).fetchone()
            if row:
                prior = BaselineDraft.model_validate_json(row[0])
                if (
                    prior.submission_digest != draft.submission_digest
                    or prior.operator_id != draft.operator_id
                ):
                    raise WorkflowError("baseline submission identifier reused")
                return prior
            if draft.inputs is not None:
                for source in draft.inputs.sources:
                    self._bind(
                        "sources", "source_id", str(source.source_id), source.model_dump_json()
                    )
                e = draft.inputs.evidence
                existing = self.db.execute(
                    "SELECT payload FROM extraction_attempts WHERE attempt_id=?",
                    (str(e.extraction.attempt_id),),
                ).fetchone()
                if existing and existing[0] != e.model_dump_json():
                    raise WorkflowError("extraction attempt is immutable")
                if not existing:
                    self.db.execute(
                        "INSERT INTO extraction_attempts VALUES (?,?,?)",
                        (str(e.extraction.attempt_id), str(e.request_id), e.model_dump_json()),
                    )
            self.db.execute(
                "INSERT INTO baseline_drafts VALUES (?,?)",
                (str(draft.draft_id), draft.model_dump_json()),
            )
            return draft

    def get_baseline_draft(self, draft_id: UUID) -> BaselineDraft:
        row = self.db.execute(
            "SELECT payload FROM baseline_drafts WHERE draft_id=?", (str(draft_id),)
        ).fetchone()
        if row is None:
            raise WorkflowError("baseline draft not found")
        return BaselineDraft.model_validate_json(row[0])

    def assert_baseline(self, action: BaselineAssertion) -> TrustedVendorRecord:
        action = BaselineAssertion.model_validate(action.model_dump())
        digest = sha256(action.model_dump_json().encode()).hexdigest()
        with self._transaction():
            draft = self.get_baseline_draft(action.draft_id)
            prior = self.db.execute(
                "SELECT * FROM baseline_assertions WHERE draft_id=?", (str(action.draft_id),)
            ).fetchone()
            if prior:
                if prior["action_sha256"] != digest:
                    raise WorkflowError("baseline assertion already recorded differently")
                record = self.get_vendor(draft.vendor_id)
                if str(record.revision_id) != prior["vendor_revision_id"]:
                    raise WorkflowError("baseline assertion is historical; vendor has changed")
                return record
            record = trusted_record(draft, action)
            self._put_vendor(record, action.operator_id, draft.expected_vendor_revision_id)
            self.db.execute(
                "INSERT INTO baseline_assertions VALUES (?,?,?,?,?)",
                (
                    str(draft.draft_id),
                    digest,
                    action.model_dump_json(),
                    str(record.revision_id),
                    datetime.now(UTC).isoformat(),
                ),
            )
            return record

    def verification_receipt(self, case_id: UUID, event_id: UUID) -> dict[str, object]:
        with self._transaction():
            current = self.get_case(case_id)
            row = self.db.execute(
                "SELECT payload, resulting_revision_id FROM verification_attempts WHERE case_id=? AND event_id=?",
                (str(case_id), str(event_id)),
            ).fetchone()
            if row is None:
                raise WorkflowError("verification receipt not found")
            event = IndependentCheckEvent.model_validate_json(row[0])
            recorded = self.get_case(case_id, event.source_revision_id)
            snapshot = recorded.snapshot
            if (
                snapshot.comparison is None
                or snapshot.baseline is None
                or snapshot.comparison.comparison_id != event.comparison_id
                or snapshot.baseline.revision_id != event.baseline_revision_id
                or snapshot.baseline.callback_contact != event.trusted_contact
                or snapshot.comparison.requested_identity != event.checked_identity
            ):
                raise WorkflowError("receipt does not match its recorded comparison")
            result = current.snapshot.comparison
            active = (
                not current.stale
                and row["resulting_revision_id"] == str(current.revision_id)
                and result is not None
                and result.comparison_id == event.comparison_id
            )
            if event.confirmation is not None:
                active = active and current.snapshot.verification == event.confirmation
            return {
                "receipt_version": "human-attestation-v1",
                "event": event.model_dump(mode="json"),
                "snapshot": snapshot.model_dump(mode="json"),
                "case_revision_id": str(event.source_revision_id),
                "case_version": recorded.version,
                "recorded_comparison_state": snapshot.comparison.state,
                "generated_at": datetime.now(UTC).isoformat(),
                "current": active,
                "status": "CURRENT" if active else "HISTORICAL_STALE",
                "comparison_state": result.state if result and active else None,
                "payment_authorization": "NOT_PROVIDED",
                "account_ownership": "NOT_ESTABLISHED",
            }
