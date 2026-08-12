"""Persist Enter submissions and their capture diagnostics."""

from __future__ import annotations

from datetime import datetime
import json
import uuid
from typing import Any

from .config import config
from .database import CaptureDiagnosticRecord, Database, InputRecord


def save_submission_event(db: Database, event: Any, content: str) -> int:
    """Save submitted text without persisting captured UI context."""
    submission_id = event.modifiers.get("submission_id") or f"sub-{uuid.uuid4().hex}"
    session_id = f"submit-{submission_id}"
    redacted_content = bool(event.modifiers.get("redacted_content"))
    char_count = int(event.modifiers.get("char_count_override") or len(content))
    stored_content = "" if config.input_capture_mode == "count-only" or redacted_content else content
    input_id = db.save_input_record(
        InputRecord(
            id=None,
            timestamp=event.timestamp,
            app_name=event.app_name,
            app_bundle_id=event.app_bundle_id,
            display_name=config.get_app_display_name(event.app_bundle_id, event.app_name),
            content=stored_content,
            char_count=char_count,
            session_id=session_id,
            duration_seconds=0,
        )
    )

    _save_persisted_capture_diagnostic(
        db,
        event,
        redacted_content=redacted_content,
        stored_content=stored_content,
    )

    return input_id


def _save_persisted_capture_diagnostic(
    db: Database,
    event: Any,
    *,
    redacted_content: bool,
    stored_content: str,
):
    modifiers = event.modifiers or {}
    source = modifiers.get("fallback_source") or "ax_value"
    decision_action = (
        "persist_count"
        if redacted_content or config.input_capture_mode == "count-only" or not stored_content
        else "persist_text"
    )
    physical_key_count = modifiers.get("physical_key_count")
    if physical_key_count is None and modifiers.get("char_count_override") is not None:
        physical_key_count = modifiers.get("char_count_override")
    context_data = modifiers.get("context") or {}
    diagnostic_details = {
        "submission_id": modifiers.get("submission_id"),
        "redacted_content": redacted_content,
        "input_capture_mode": config.input_capture_mode,
    }
    extra_diagnostics = modifiers.get("capture_diagnostics")
    if isinstance(extra_diagnostics, dict):
        diagnostic_details.update(extra_diagnostics)
    db.save_capture_diagnostic(
        CaptureDiagnosticRecord(
            id=None,
            timestamp=event.timestamp,
            app_name=event.app_name,
            app_bundle_id=event.app_bundle_id,
            event_type="enter_submission",
            decision_action=decision_action,
            decision_reason="saved_submission",
            selected_source=source,
            selected_confidence=1.0 if decision_action == "persist_text" else None,
            physical_key_count=physical_key_count,
            focused_role=None,
            focused_subrole=None,
            capture_status=context_data.get("capture_status", "ok"),
            diagnostics_json=_json_or_none(diagnostic_details),
        )
    )


def save_capture_diagnostic_event(db: Database, diagnostic: dict) -> int:
    """Persist a listener-level capture diagnostic event."""
    return db.save_capture_diagnostic(
        CaptureDiagnosticRecord(
            id=None,
            timestamp=diagnostic["timestamp"],
            app_name=diagnostic["app_name"],
            app_bundle_id=diagnostic["app_bundle_id"],
            event_type=diagnostic["event_type"],
            decision_action=diagnostic["decision_action"],
            decision_reason=diagnostic["decision_reason"],
            selected_source=diagnostic.get("selected_source"),
            selected_confidence=diagnostic.get("selected_confidence"),
            physical_key_count=diagnostic.get("physical_key_count"),
            focused_role=None,
            focused_subrole=None,
            capture_status=diagnostic.get("capture_status", "ok"),
            diagnostics_json=_json_or_none(diagnostic.get("diagnostics")),
        )
    )


def _json_or_none(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
