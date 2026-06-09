"""Screenshot capture helpers for submission context."""

from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
import subprocess

from .context_capture import AXFrame, CapturedContext, choose_screenshot_scope


@dataclass
class ScreenshotCaptureResult:
    path: Path | None
    scope: str
    status: str
    error: str | None = None


def build_screenshot_path(base_dir: Path, timestamp: datetime, submission_id: str) -> Path:
    return (
        Path(base_dir)
        / f"{timestamp.year:04d}"
        / f"{timestamp.month:02d}"
        / f"{timestamp.day:02d}"
        / f"{submission_id}.png"
    )


def screenshot_region_args(frame: AXFrame | None) -> str | None:
    if frame is None:
        return None
    return f"{round(frame.x)},{round(frame.y)},{round(frame.width)},{round(frame.height)}"


def capture_context_screenshot(
    context: CapturedContext,
    submission_id: str,
    timestamp: datetime,
    base_dir: Path,
    max_width: int = 1600,
) -> ScreenshotCaptureResult:
    """Capture the selected context region to a PNG file."""
    scope = choose_screenshot_scope(context)
    output_path = build_screenshot_path(base_dir, timestamp, submission_id)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    result = capture_region_to_png(scope.frame, output_path, max_width=max_width)
    if result.status != "ok":
        return ScreenshotCaptureResult(None, scope.scope, result.status, result.error)
    return ScreenshotCaptureResult(output_path, scope.scope, "ok")


def capture_region_to_png(
    frame: AXFrame | None,
    output_path: Path,
    max_width: int = 1600,
) -> ScreenshotCaptureResult:
    """Capture with macOS screencapture; full screen when frame is None."""
    cmd = ["/usr/sbin/screencapture", "-x"]
    region = screenshot_region_args(_scale_frame_to_max_width(frame, max_width))
    if region is not None:
        cmd.extend(["-R", region])
    cmd.append(str(output_path))

    try:
        completed = subprocess.run(cmd, capture_output=True, text=True, timeout=10, check=False)
    except subprocess.TimeoutExpired:
        return ScreenshotCaptureResult(None, "unknown", "timeout", "screencapture timed out")
    except Exception as exc:
        return ScreenshotCaptureResult(None, "unknown", "failed", str(exc))

    if completed.returncode != 0:
        error = completed.stderr.strip() or completed.stdout.strip() or f"exit {completed.returncode}"
        return ScreenshotCaptureResult(None, "unknown", "screenshot_denied", error)

    return ScreenshotCaptureResult(output_path, "unknown", "ok")


def _scale_frame_to_max_width(frame: AXFrame | None, max_width: int) -> AXFrame | None:
    if frame is None or max_width <= 0 or frame.width <= max_width:
        return frame
    scale = max_width / frame.width
    return AXFrame(frame.x, frame.y, max_width, frame.height * scale)
