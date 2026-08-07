from datetime import datetime, timedelta, timezone

from ominime import runtime_state


def test_runtime_state_is_shared_through_disk(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime-state.json"
    monkeypatch.setattr(runtime_state, "_state_file_path", state_path)
    runtime_state.reset_runtime_state()

    written = runtime_state.set_recording_status("recording")
    monkeypatch.setattr(runtime_state, "_state", runtime_state.RuntimeState())

    loaded = runtime_state.get_runtime_state()
    assert loaded.recording_status == "recording"
    assert loaded.process_id == written.process_id
    assert loaded.heartbeat_at is not None


def test_stale_recording_heartbeat_reports_unknown(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime-state.json"
    monkeypatch.setattr(runtime_state, "_state_file_path", state_path)
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runtime_state, "_utcnow", lambda: now)
    runtime_state.reset_runtime_state()
    runtime_state.set_recording_status("recording")

    monkeypatch.setattr(
        runtime_state,
        "_utcnow",
        lambda: now + timedelta(seconds=runtime_state.RUNTIME_HEARTBEAT_TTL_SECONDS + 1),
    )
    monkeypatch.setattr(runtime_state, "_state", runtime_state.RuntimeState())

    loaded = runtime_state.get_runtime_state()
    assert loaded.recording_status == "unknown"
    assert loaded.is_recording is False
    assert loaded.last_error == "stale_heartbeat"


def test_refresh_runtime_heartbeat_keeps_recording_state_fresh(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime-state.json"
    monkeypatch.setattr(runtime_state, "_state_file_path", state_path)
    now = datetime(2026, 8, 6, 12, 0, tzinfo=timezone.utc)
    monkeypatch.setattr(runtime_state, "_utcnow", lambda: now)
    runtime_state.reset_runtime_state()
    runtime_state.set_recording_status("recording")

    refreshed_at = now + timedelta(seconds=30)
    monkeypatch.setattr(runtime_state, "_utcnow", lambda: refreshed_at)
    refreshed = runtime_state.refresh_runtime_heartbeat()

    assert refreshed.recording_status == "recording"
    assert refreshed.heartbeat_at == refreshed_at


def test_invalid_shared_state_degrades_to_visible_unknown(tmp_path, monkeypatch):
    state_path = tmp_path / "runtime-state.json"
    monkeypatch.setattr(runtime_state, "_state_file_path", state_path)
    state_path.write_text("not-json", encoding="utf-8")
    monkeypatch.setattr(runtime_state, "_state", runtime_state.RuntimeState())

    loaded = runtime_state.get_runtime_state()

    assert loaded.recording_status == "unknown"
    assert loaded.last_error == "runtime_state_unreadable"
