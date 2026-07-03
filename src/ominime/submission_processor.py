"""Persist Enter submissions and run optional multimodal context analysis."""

from __future__ import annotations

from datetime import datetime
import json
import threading
import uuid
from typing import Any

from .config import config
from .database import Database, InputRecord, SubmissionContextRecord
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

    if should_analyze:
        _start_analysis_thread(db, submission_id, stored_content, event, context_data)

    return input_id


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
