from datetime import date, datetime

from ominime import database as database_module
from ominime import time_utils
from ominime.database import Database, InputRecord


def save_record(db: Database, timestamp: datetime, chars: int):
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


def test_daily_queries_use_beijing_day_boundaries_with_new_york_storage(tmp_path, monkeypatch):
    monkeypatch.setattr(time_utils.config, "day_timezone", "Asia/Shanghai", raising=False)
    monkeypatch.setattr(time_utils.config, "storage_timezone", "America/New_York", raising=False)
    db = Database(tmp_path / "test.db")

    save_record(db, datetime(2026, 6, 26, 11, 59, 59), chars=2)
    save_record(db, datetime(2026, 6, 26, 12, 0, 0), chars=3)
    save_record(db, datetime(2026, 6, 27, 11, 59, 59), chars=5)
    save_record(db, datetime(2026, 6, 27, 12, 0, 0), chars=7)

    records = db.get_records_by_date(date(2026, 6, 27))
    stats = db.get_daily_stats(date(2026, 6, 27))

    assert [record.char_count for record in records] == [3, 5]
    assert sum(stat.total_chars for stat in stats) == 8


def test_total_chars_today_uses_business_today_window(tmp_path, monkeypatch):
    monkeypatch.setattr(time_utils.config, "day_timezone", "Asia/Shanghai", raising=False)
    monkeypatch.setattr(time_utils.config, "storage_timezone", "America/New_York", raising=False)
    monkeypatch.setattr(database_module, "business_today", lambda: date(2026, 6, 27))
    db = Database(tmp_path / "test.db")

    save_record(db, datetime(2026, 6, 26, 11, 59, 59), chars=11)
    save_record(db, datetime(2026, 6, 26, 12, 0, 0), chars=13)
    save_record(db, datetime(2026, 6, 27, 11, 59, 59), chars=17)

    assert db.get_total_chars_today() == 30
