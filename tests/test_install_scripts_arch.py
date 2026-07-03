import platform
import shlex
import subprocess
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


def _read(path: str) -> str:
    return (ROOT / path).read_text()


def test_native_python_selector_returns_apple_silicon_python_on_apple_silicon():
    if platform.machine() != "arm64":
        return

    helper = ROOT / "scripts" / "native_python.sh"
    command = (
        f"source {shlex.quote(str(helper))}; "
        "python_path=$(ominime_select_python); "
        "printf '%s\\n' \"$python_path\"; "
        "\"$python_path\" -c 'import platform; print(platform.machine())'"
    )

    result = subprocess.run(
        ["bash", "-lc", command],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    selected_python, selected_arch = result.stdout.strip().splitlines()
    assert selected_python.endswith("python3")
    assert selected_arch in {"arm64", "arm64e"}


def test_install_entrypoints_use_native_python_selector():
    assert "ominime_select_python" in _read("scripts/install.sh")
    assert "ominime_select_python" in _read("scripts/install_app.sh")


def test_launchagent_scripts_validate_venv_python_architecture():
    assert "ominime_require_native_python" in _read("src/ominime/scripts/install_app.sh")
    assert "ominime_require_native_python" in _read("src/ominime/scripts/install_web.sh")
    assert "ominime_require_native_python" in _read("src/ominime/scripts/daily_export.sh")


def test_launchagent_path_prefers_apple_silicon_homebrew():
    assert "/opt/homebrew/bin:/usr/local/bin" in _read("src/ominime/scripts/install_app.sh")
    assert "/opt/homebrew/bin:/usr/local/bin" in _read("src/ominime/scripts/install_web.sh")
