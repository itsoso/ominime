from datetime import datetime
import json

from ominime.database import Database, InputRecord, SubmissionContextRecord


def test_save_submission_context_links_input_record(tmp_path):
    db = Database(tmp_path / "test.db")
    input_id = db.save_input_record(
        InputRecord(
            id=None,
            timestamp=datetime(2026, 6, 9, 12, 0, 0),
            app_name="Codex",
            app_bundle_id="com.openai.codex",
            display_name="Codex",
            content="帮我实现上下文保存",
            char_count=10,
            session_id="submit-1",
            duration_seconds=0,
        )
    )
    context_id = db.save_submission_context(
        SubmissionContextRecord(
            id=None,
            submission_id="sub-1",
            input_record_id=input_id,
            timestamp=datetime(2026, 6, 9, 12, 0, 0),
            app_name="Codex",
            app_bundle_id="com.openai.codex",
            window_title="OmniMe",
            focused_role="AXTextArea",
            focused_frame_json=json.dumps({"x": 1}),
            container_role="AXGroup",
            container_frame_json=json.dumps({"x": 2}),
            ax_hierarchy_json=json.dumps([{"role": "AXTextArea"}]),
            screenshot_path="/tmp/sub-1.png",
            screenshot_scope="container",
            qwen_analysis_json=json.dumps({"context_type": "chat"}),
            qwen_model="Qwen/Qwen2.5-VL-7B-Instruct",
            analysis_status="ok",
            capture_status="ok",
        )
    )
    assert context_id > 0

    saved = db.get_submission_context("sub-1")
    assert saved is not None
    assert saved.input_record_id == input_id
    assert saved.screenshot_path == "/tmp/sub-1.png"
    assert saved.analysis_status == "ok"


def test_get_recent_submission_contexts_returns_joined_content(tmp_path):
    db = Database(tmp_path / "test.db")
    input_id = db.save_input_record(
        InputRecord(
            id=None,
            timestamp=datetime(2026, 6, 9, 12, 0, 0),
            app_name="Codex",
            app_bundle_id="com.openai.codex",
            display_name="Codex",
            content="完整输入内容",
            char_count=6,
            session_id="submit-2",
            duration_seconds=0,
        )
    )
    db.save_submission_context(
        SubmissionContextRecord(
            id=None,
            submission_id="sub-2",
            input_record_id=input_id,
            timestamp=datetime(2026, 6, 9, 12, 0, 0),
            app_name="Codex",
            app_bundle_id="com.openai.codex",
            capture_status="ok",
            analysis_status="pending",
        )
    )
    rows = db.get_recent_submission_contexts(limit=5)
    assert rows[0]["content"] == "完整输入内容"
    assert rows[0]["submission_id"] == "sub-2"
