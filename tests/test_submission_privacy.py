from datetime import datetime
from types import SimpleNamespace

from ominime.database import Database
from ominime import submission_processor


def make_event(modifiers=None):
    event_modifiers = {
        "submission_id": "privacy-mode-test",
        "context": {},
    }
    if modifiers:
        event_modifiers.update(modifiers)
    return SimpleNamespace(
        timestamp=datetime(2026, 6, 20, 9, 0, 0),
        app_name="Codex",
        app_bundle_id="com.openai.codex",
        modifiers=event_modifiers,
    )


def test_count_only_mode_records_count_without_raw_content(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    content = "private prompt content"
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "count-only",
        raising=False,
    )

    submission_processor.save_submission_event(db, make_event(), content)

    records = db.get_records_by_date(datetime(2026, 6, 20).date())
    assert len(records) == 1
    assert records[0].char_count == len(content)
    assert records[0].content == ""


def test_redacted_submission_uses_count_override_without_raw_content(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    event = make_event()
    event.modifiers.update(
        {
            "redacted_content": True,
            "char_count_override": 7,
        }
    )
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "enter-text",
        raising=False,
    )

    submission_processor.save_submission_event(db, event, "[unreadable input]")

    records = db.get_records_by_date(datetime(2026, 6, 20).date())
    assert len(records) == 1
    assert records[0].char_count == 7
    assert records[0].content == ""


def test_submission_never_starts_multimodal_analysis(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    analysis_calls = []
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "enter-text",
        raising=False,
    )
    monkeypatch.setattr(
        submission_processor.config,
        "multimodal_context_analysis",
        True,
        raising=False,
    )
    monkeypatch.setattr(
        submission_processor,
        "_start_analysis_thread",
        lambda *args: analysis_calls.append(args),
        raising=False,
    )

    submission_processor.save_submission_event(db, make_event(), "local only")

    assert analysis_calls == []


def test_new_submission_does_not_persist_context_metadata(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    event = make_event(
        {
            "submission_id": "no-new-context",
            "context": {
                "window_title": "Private chat",
                "focused_role": "AXTextArea",
                "focused_subrole": "AXStandardTextArea",
                "container_role": "AXGroup",
            },
        }
    )
    monkeypatch.setattr(
        submission_processor.config,
        "input_capture_mode",
        "enter-text",
        raising=False,
    )

    input_id = submission_processor.save_submission_event(db, event, "local text")

    assert db.get_latest_input_record().id == input_id
    assert db.get_latest_input_record().content == "local text"
    assert db.get_submission_context("no-new-context") is None
    diagnostic = db.get_recent_capture_diagnostics(limit=1)[0]
    assert diagnostic["focused_role"] is None
    assert diagnostic["focused_subrole"] is None
