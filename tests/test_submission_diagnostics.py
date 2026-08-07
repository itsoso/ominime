from datetime import datetime
from types import SimpleNamespace

from ominime.database import Database
from ominime import submission_processor


def make_event(**modifiers):
    return SimpleNamespace(
        timestamp=datetime(2026, 7, 5, 10, 0, 0),
        app_name="Codex",
        app_bundle_id="com.openai.codex",
        modifiers={"submission_id": "diag-sub-1", "context": {}, **modifiers},
    )


def test_saved_submission_writes_capture_diagnostic(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "enter-text",
        raising=False,
    )

    submission_processor.save_submission_event(
        db,
        make_event(fallback_source="key_event_text"),
        "你好",
    )

    rows = db.get_recent_capture_diagnostics(limit=1)
    assert len(rows) == 1
    assert rows[0]["decision_action"] == "persist_text"
    assert rows[0]["decision_reason"] == "saved_submission"
    assert rows[0]["selected_source"] == "key_event_text"
    assert rows[0]["app_name"] == "Codex"


def test_redacted_submission_writes_count_diagnostic(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "enter-text",
        raising=False,
    )

    submission_processor.save_submission_event(
        db,
        make_event(
            fallback_source="count_unreadable",
            redacted_content=True,
            char_count_override=7,
        ),
        "[unreadable input]",
    )

    rows = db.get_recent_capture_diagnostics(limit=1)
    assert rows[0]["decision_action"] == "persist_count"
    assert rows[0]["decision_reason"] == "saved_submission"
    assert rows[0]["selected_source"] == "count_unreadable"
    assert rows[0]["physical_key_count"] == 7


def test_save_capture_diagnostic_event_persists_listener_skip(tmp_path):
    db = Database(tmp_path / "test.db")

    submission_processor.save_capture_diagnostic_event(
        db,
        {
            "timestamp": datetime(2026, 7, 5, 10, 1, 0),
            "app_name": "Claude",
            "app_bundle_id": "com.anthropic.claudefordesktop",
            "event_type": "enter_keydown",
            "decision_action": "skip",
            "decision_reason": "no_trusted_content",
            "selected_source": None,
            "selected_confidence": None,
            "physical_key_count": 0,
            "focused_role": None,
            "focused_subrole": None,
            "capture_status": "ok",
            "diagnostics": {"clipboard_copy_attempted": False},
        },
    )

    rows = db.get_recent_capture_diagnostics(limit=1)
    assert rows[0]["decision_action"] == "skip"
    assert rows[0]["decision_reason"] == "no_trusted_content"
    assert rows[0]["diagnostics_json"] == '{"clipboard_copy_attempted": false}'
