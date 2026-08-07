from datetime import datetime

from ominime.database import CaptureDiagnosticRecord, Database


def test_save_and_read_recent_capture_diagnostic(tmp_path):
    db = Database(tmp_path / "test.db")

    diagnostic_id = db.save_capture_diagnostic(
        CaptureDiagnosticRecord(
            id=None,
            timestamp=datetime(2026, 7, 5, 10, 0, 0),
            app_name="Claude",
            app_bundle_id="com.anthropic.claudefordesktop",
            event_type="enter_keydown",
            decision_action="skip",
            decision_reason="unsafe_clipboard_rejected",
            selected_source=None,
            selected_confidence=None,
            physical_key_count=3,
            focused_role=None,
            focused_subrole=None,
            capture_status="ok",
            diagnostics_json='{"source":"clipboard"}',
        )
    )

    assert diagnostic_id > 0
    rows = db.get_recent_capture_diagnostics(limit=1)
    assert len(rows) == 1
    assert rows[0]["decision_action"] == "skip"
    assert rows[0]["decision_reason"] == "unsafe_clipboard_rejected"
    assert rows[0]["physical_key_count"] == 3
    assert rows[0]["diagnostics_json"] == '{"source":"clipboard"}'
