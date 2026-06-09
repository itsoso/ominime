"""Accessibility context capture primitives."""

from dataclasses import dataclass, field


@dataclass(frozen=True)
class AXFrame:
    x: float
    y: float
    width: float
    height: float

    def to_dict(self) -> dict[str, float]:
        return {
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
        }


@dataclass(frozen=True)
class ScreenshotScope:
    scope: str
    frame: AXFrame | None


@dataclass
class CapturedContext:
    focused_frame: AXFrame | None = None
    container_frame: AXFrame | None = None
    window_frame: AXFrame | None = None
    hierarchy: list[dict] = field(default_factory=list)
    capture_status: str = "ok"
    capture_error: str | None = None


def choose_screenshot_scope(context: CapturedContext) -> ScreenshotScope:
    """Choose the smallest useful region available for screenshot capture."""
    if context.container_frame is not None:
        return ScreenshotScope("container", context.container_frame)
    if context.window_frame is not None:
        return ScreenshotScope("window", context.window_frame)
    return ScreenshotScope("screen", None)
