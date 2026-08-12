import json

from ominime.config import AppConfig


def test_saved_config_has_no_multimodal_qwen_fields(tmp_path):
    config = AppConfig(
        data_dir=tmp_path,
        db_path=tmp_path / "ominime.db",
        log_dir=tmp_path / "logs",
    )
    path = tmp_path / "config.json"

    config.save(path)

    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "multimodal_context_analysis" not in payload
    assert "multimodal_backend" not in payload
    assert not any(key.startswith("qwen_vl_") for key in payload)


def test_api_key_does_not_enable_remote_ai_without_explicit_consent(tmp_path, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "secret")

    config = AppConfig(
        data_dir=tmp_path,
        db_path=tmp_path / "ominime.db",
        log_dir=tmp_path / "logs",
    )

    assert config.openai_api_key == "secret"
    assert config.ai_enabled is False
