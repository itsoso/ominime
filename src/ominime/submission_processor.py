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
    input_id = db.save_input_record(
        InputRecord(
            id=None,
            timestamp=event.timestamp,
            app_name=event.app_name,
            app_bundle_id=event.app_bundle_id,
            display_name=config.get_app_display_name(event.app_bundle_id, event.app_name),
            content=content,
            char_count=len(content),
            session_id=session_id,
            duration_seconds=0,
        )
    )

    context_data = event.modifiers.get("context") or {}
    screenshot = event.modifiers.get("screenshot") or {}
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
            screenshot_path=screenshot.get("path"),
            screenshot_scope=screenshot.get("scope"),
            analysis_status="pending" if config.multimodal_context_analysis else "disabled",
            capture_status=context_data.get("capture_status", "ok"),
            capture_error=context_data.get("capture_error") or screenshot.get("error"),
        )
    )

    if config.multimodal_context_analysis:
        _start_analysis_thread(db, submission_id, content, event, context_data, screenshot)

    return input_id


def _start_analysis_thread(
    db: Database,
    submission_id: str,
    content: str,
    event: Any,
    context_data: dict,
    screenshot: dict,
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
            "screenshot_scope": screenshot.get("scope"),
        }
        response = backend.analyze_context(
            MultimodalAnalysisRequest(
                submitted_text=content,
                screenshot_path=screenshot.get("path"),
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
