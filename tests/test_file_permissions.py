import stat

from ominime.config import AppConfig
from ominime.database import Database
from ominime import runtime_state


def mode(path):
    return stat.S_IMODE(path.stat().st_mode)


def test_sensitive_local_paths_are_private(tmp_path, monkeypatch):
    data_dir = tmp_path / "data"
    config = AppConfig(
        data_dir=data_dir,
        db_path=data_dir / "ominime.db",
        log_dir=data_dir / "logs",
    )
    config_path = data_dir / "config.json"
    config.save(config_path)
    Database(config.db_path)
    state_path = data_dir / "runtime-state.json"
    monkeypatch.setattr(runtime_state, "_state_file_path", state_path)
    runtime_state.set_recording_status("recording")

    assert mode(data_dir) == 0o700
    assert mode(config.log_dir) == 0o700
    assert mode(config_path) == 0o600
    assert mode(config.db_path) == 0o600
    assert mode(state_path) == 0o600
