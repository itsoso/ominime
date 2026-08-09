"""Persist Enter submissions and run optional multimodal context analysis."""

from __future__ import annotations

from datetime import datetime
import json
import threading
import uuid
from typing import Any

from .config import config
from .database import CaptureDiagnosticRecord, Database, InputRecord, SubmissionContextRecord
from .multimodal_backend import MultimodalAnalysisRequest, get_multimodal_backend


def save_submission_event(db: Database, event: Any, content: str) -> int:
    """Save submitted text and linked context metadata."""
    submission_id = event.modifiers.get("submission_id") or f"sub-{uuid.uuid4().hex}"
    session_id = f"submit-{submission_id}"
    redacted_content = bool(event.modifiers.get("redacted_content"))
    char_count = int(event.modifiers.get("char_count_override") or len(content))
    stored_content = "" if config.input_capture_mode == "count-only" or redacted_content else content
    should_analyze = bool(config.multimodal_context_analysis and stored_content)
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

    context_data = event.modifiers.get("context") or {}
    db.save_submission_context(
        SubmissionContextRecord(
            id=None,
            submission_id=submission_id,
            input_record_id=input_id,
            timestamp=event.timestamp,
            app_name=event.app_name,
            app_bundle_id=event.app_bundle_id,
            window_title=context_data.get("window_title"),
            focused_role=context_data.get("focused_role"),
            focused_subrole=context_data.get("focused_subrole"),
            focused_title=context_data.get("focused_title"),
            focused_description=context_data.get("focused_description"),
            focused_identifier=context_data.get("focused_identifier"),
            focused_frame_json=_json_or_none(context_data.get("focused_frame")),
            container_role=context_data.get("container_role"),
            container_title=context_data.get("container_title"),
            container_frame_json=_json_or_none(context_data.get("container_frame")),
            ax_hierarchy_json=_json_or_none(context_data.get("hierarchy")),
            analysis_status="pending" if should_analyze else "disabled",
            capture_status=context_data.get("capture_status", "ok"),
            capture_error=context_data.get("capture_error"),
        )
    )
    _save_persisted_capture_diagnostic(
        db,
        event,
        redacted_content=redacted_content,
        stored_content=stored_content,
    )

    if should_analyze:
        _start_analysis_thread(db, submission_id, stored_content, event, context_data)

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
            focused_role=context_data.get("focused_role"),
            focused_subrole=context_data.get("focused_subrole"),
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
            focused_role=diagnostic.get("focused_role"),
            focused_subrole=diagnostic.get("focused_subrole"),
            capture_status=diagnostic.get("capture_status", "ok"),
            diagnostics_json=_json_or_none(diagnostic.get("diagnostics")),
        )
    )


def _start_analysis_thread(
    db: Database,
    submission_id: str,
    content: str,
    event: Any,
    context_data: dict,
):
    def run():
        backend = get_multimodal_backend()
        if backend is None:
            db.update_submission_context_analysis(
                submission_id,
                analysis_status="disabled",
                analysis_error="multimodal backend disabled",
            )
            return

        metadata = {
            "app_name": event.app_name,
            "app_bundle_id": event.app_bundle_id,
            "window_title": context_data.get("window_title"),
            "focused_element": {
                "role": context_data.get("focused_role"),
                "subrole": context_data.get("focused_subrole"),
                "title": context_data.get("focused_title"),
                "description": context_data.get("focused_description"),
                "identifier": context_data.get("focused_identifier"),
                "frame": context_data.get("focused_frame"),
            },
            "container": {
                "role": context_data.get("container_role"),
                "title": context_data.get("container_title"),
                "frame": context_data.get("container_frame"),
            },
            "ax_hierarchy": context_data.get("hierarchy", []),
        }
        response = backend.analyze_context(
            MultimodalAnalysisRequest(
                submitted_text=content,
                screenshot_path=None,
                metadata=metadata,
            )
        )
        db.update_submission_context_analysis(
            submission_id,
            analysis_status=response.status,
            qwen_analysis_json=_json_or_none(response.analysis_json),
            qwen_raw_output=response.raw_output,
            qwen_model=response.model,
            analysis_error=response.error,
        )

    threading.Thread(target=run, daemon=True).start()


def _json_or_none(value) -> str | None:
    if value is None:
        return None
    return json.dumps(value, ensure_ascii=False)
