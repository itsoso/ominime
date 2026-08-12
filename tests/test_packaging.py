from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def test_install_metadata_contains_all_runtime_web_dependencies():
    setup = (ROOT / "setup.py").read_text(encoding="utf-8")

    for dependency in ("fastapi", "uvicorn", "pydantic", "python-dotenv", "requests"):
        assert dependency in setup

    assert '"ai"' not in setup


def test_requirements_delegates_to_the_package_metadata():
    requirements = (ROOT / "requirements.txt").read_text(encoding="utf-8")

    assert requirements.strip().endswith("-e .")
    assert "openai>=" not in requirements


def test_pytest_collects_only_the_tests_directory():
    pytest_config = (ROOT / "pytest.ini").read_text(encoding="utf-8")

    assert "testpaths = tests" in pytest_config


def test_example_environment_is_local_only():
    example = (ROOT / ".env.example").read_text(encoding="utf-8")

    assert "OPENAI_API_KEY" not in example
    assert "LLM_BACKEND=ollama" in example
    assert "127.0.0.1" in example
