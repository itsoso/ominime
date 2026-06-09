from datetime import datetime

from ominime.context_capture import AXFrame, CapturedContext
from ominime.screenshot_capture import build_screenshot_path, screenshot_region_args


def test_build_screenshot_path_uses_date_and_submission_id(tmp_path):
    path = build_screenshot_path(
        base_dir=tmp_path,
        timestamp=datetime(2026, 6, 9, 12, 0, 0),
        submission_id="abc123",
    )
    assert path == tmp_path / "2026" / "06" / "09" / "abc123.png"


def test_screenshot_region_args_rounds_frame_values():
    args = screenshot_region_args(AXFrame(1.2, 2.6, 300.4, 400.8))
    assert args == "1,3,300,401"


def test_screenshot_region_args_returns_none_for_full_screen_scope():
    context = CapturedContext()
    assert screenshot_region_args(context.container_frame) is None
