from datetime import date, datetime

from ominime.database import Database, InputRecord


def save_record(
    db,
    *,
    bundle_id,
    display_name,
    content,
    duration_seconds=0,
    session_id="session-1",
):
    db.save_input_record(
        InputRecord(
            id=None,
            timestamp=datetime(2026, 8, 11, 10, 0, 0),
            app_name="Electron",
            app_bundle_id=bundle_id,
            display_name=display_name,
            content=content,
            char_count=len(content),
            session_id=session_id,
            duration_seconds=duration_seconds,
        )
    )


def test_zero_duration_submission_is_not_counted_as_one_minute(tmp_path):
    db = Database(tmp_path / "test.db")
    save_record(
        db,
        bundle_id="app.a",
        display_name="App A",
        content="a long enough sample",
    )

    stats = db.get_daily_stats(date(2026, 8, 11))

    assert stats[0].total_time_minutes == 0


def test_daily_stats_keep_samples_isolated_by_bundle_id(tmp_path):
    db = Database(tmp_path / "test.db")
    save_record(
        db,
        bundle_id="app.a",
        display_name="App A",
        content="alpha content unique",
    )
    save_record(
        db,
        bundle_id="app.b",
        display_name="App B",
        content="beta content unique",
        session_id="session-2",
    )

    stats = {item.display_name: item for item in db.get_daily_stats(date(2026, 8, 11))}

    assert stats["App A"].sample_content == ["alpha content unique"]
    assert stats["App B"].sample_content == ["beta content unique"]


def test_database_connections_enable_integrity_and_wal_pragmas(tmp_path):
    db = Database(tmp_path / "test.db")

    with db._get_connection() as conn:
        foreign_keys = conn.execute("PRAGMA foreign_keys").fetchone()[0]
        busy_timeout = conn.execute("PRAGMA busy_timeout").fetchone()[0]
        journal_mode = conn.execute("PRAGMA journal_mode").fetchone()[0]

    assert foreign_keys == 1
    assert busy_timeout >= 5_000
    assert journal_mode.lower() == "wal"
