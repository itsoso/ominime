from datetime import date, datetime, timedelta
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from ominime.database import Database, InputRecord
from ominime import database as database_module
from ominime import runtime_state
from ominime.web import api as web_api


@pytest.fixture(autouse=True)
def reset_runtime_state():
    runtime_state.reset_runtime_state()
    yield
    runtime_state.reset_runtime_state()


def save_record(db: Database, timestamp: datetime, chars: int = 12):
    return db.save_input_record(
        InputRecord(
            id=None,
            timestamp=timestamp,
            app_name="Codex",
            app_bundle_id="com.openai.codex",
            display_name="Codex",
            content="x" * chars,
            char_count=chars,
            session_id=f"session-{timestamp.isoformat()}",
            duration_seconds=0,
        )
    )


def install_test_api_state(monkeypatch, db: Database, tmp_path):
    monkeypatch.setattr(web_api, "get_database", lambda: db)
    monkeypatch.setattr(
        web_api,
        "config",
        SimpleNamespace(
            db_path=tmp_path / "test.db",
            data_dir=tmp_path,
            input_capture_mode="enter-text",
            capture_context_on_enter=True,
            multimodal_context_analysis=False,
        ),
    )


def test_health_reports_current_capture_state_and_recent_records(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    today = date(2026, 6, 27)
    monkeypatch.setattr(database_module, "business_today", lambda: today)
    monkeypatch.setattr(web_api, "business_today", lambda: today)
    save_record(db, datetime(2026, 6, 26, 12, 0, 0), chars=15)
    install_test_api_state(monkeypatch, db, tmp_path)
    runtime_state.set_recording_status("recording")

    response = TestClient(web_api.app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "running"
    assert payload["is_recording"] is True
    assert payload["recording_status"] == "recording"
    assert payload["input_capture_mode"] == "enter-text"
    assert payload["today_date"] == "2026-06-27"
    assert payload["today_chars"] == 15
    assert payload["last_recorded_at"].startswith("2026-06-26T12:00:00")


def test_status_includes_non_misleading_recording_status(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    install_test_api_state(monkeypatch, db, tmp_path)
    runtime_state.set_recording_status("recording")

    response = TestClient(web_api.app).get("/api/status")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_recording"] is True
    assert payload["recording_status"] == "recording"
    assert payload["input_capture_mode"] == "enter-text"


def test_health_defaults_to_unknown_when_no_embedded_runtime_state(tmp_path, monkeypatch):
    db = Database(tmp_path / "test.db")
    install_test_api_state(monkeypatch, db, tmp_path)
    runtime_state.reset_runtime_state()

    response = TestClient(web_api.app).get("/api/health")

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_recording"] is False
    assert payload["recording_status"] == "unknown"
