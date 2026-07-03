from datetime import datetime
from types import SimpleNamespace

from ominime.database import Database
from ominime import submission_processor


def make_event():
    return SimpleNamespace(
        timestamp=datetime(2026, 6, 20, 9, 0, 0),
        app_name="Codex",
        app_bundle_id="com.openai.codex",
        modifiers={"submission_id": "privacy-mode-test", "context": {}},
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
