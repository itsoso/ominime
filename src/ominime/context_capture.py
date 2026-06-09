"""Accessibility context capture primitives."""

from dataclasses import dataclass, field
from typing import Any


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
    focused_role: str | None = None
    focused_subrole: str | None = None
    focused_title: str | None = None
    focused_description: str | None = None
    focused_identifier: str | None = None
    container_role: str | None = None
    container_title: str | None = None
    window_title: str | None = None
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


def context_to_dict(context: CapturedContext) -> dict[str, Any]:
    """Serialize captured context for event metadata and JSON storage."""
    return {
        "focused_frame": context.focused_frame.to_dict() if context.focused_frame else None,
        "container_frame": context.container_frame.to_dict() if context.container_frame else None,
        "window_frame": context.window_frame.to_dict() if context.window_frame else None,
        "focused_role": context.focused_role,
        "focused_subrole": context.focused_subrole,
        "focused_title": context.focused_title,
        "focused_description": context.focused_description,
        "focused_identifier": context.focused_identifier,
        "container_role": context.container_role,
        "container_title": context.container_title,
        "window_title": context.window_title,
        "hierarchy": context.hierarchy,
        "capture_status": context.capture_status,
        "capture_error": context.capture_error,
    }


def frame_from_dict(value: dict | None) -> AXFrame | None:
    if not isinstance(value, dict):
        return None
    required = ("x", "y", "width", "height")
    if not all(key in value for key in required):
        return None
    return AXFrame(
        float(value["x"]),
        float(value["y"]),
        float(value["width"]),
        float(value["height"]),
    )


def select_container_node(hierarchy: list[dict]) -> dict | None:
    """Select the nearest useful dialog/container ancestor."""
    if not hierarchy:
        return None

    focused_frame = frame_from_dict(hierarchy[0].get("frame"))
    window_node = None
    container_roles = {"AXGroup", "AXScrollArea", "AXSplitGroup"}

    for node in hierarchy[1:]:
        role = node.get("role")
        if role == "AXWindow":
            window_node = node
            continue
        if role not in container_roles:
            continue
        frame = frame_from_dict(node.get("frame"))
        if frame is None:
            continue
        if focused_frame is None or _is_useful_container_frame(focused_frame, frame):
            return node

    return window_node


def _is_useful_container_frame(focused: AXFrame, candidate: AXFrame) -> bool:
    if candidate.width < focused.width or candidate.height < focused.height:
        return False
    return candidate.height >= max(160, focused.height * 3)


def capture_accessibility_context(max_depth: int = 12) -> CapturedContext:
    """Capture focused element metadata through macOS Accessibility APIs."""
    try:
        focused = get_focused_element()
        if focused is None:
            return CapturedContext(capture_status="degraded", capture_error="focused element unavailable")

        hierarchy = walk_ax_hierarchy(focused, max_depth=max_depth)
        focused_node = hierarchy[0] if hierarchy else {}
        container_node = select_container_node(hierarchy)
        window_node = next((node for node in hierarchy if node.get("role") == "AXWindow"), None)

        focused_frame = frame_from_dict(focused_node.get("frame"))
        container_frame = frame_from_dict(container_node.get("frame")) if container_node else None
        window_frame = frame_from_dict(window_node.get("frame")) if window_node else None

        return CapturedContext(
            focused_frame=focused_frame,
            container_frame=container_frame,
            window_frame=window_frame,
            focused_role=focused_node.get("role"),
            focused_subrole=focused_node.get("subrole"),
            focused_title=focused_node.get("title"),
            focused_description=focused_node.get("description"),
            focused_identifier=focused_node.get("identifier"),
            container_role=container_node.get("role") if container_node else None,
            container_title=container_node.get("title") if container_node else None,
            window_title=window_node.get("title") if window_node else None,
            hierarchy=hierarchy,
        )
    except Exception as exc:
        return CapturedContext(capture_status="degraded", capture_error=str(exc))


def get_focused_element():
    try:
        from ApplicationServices import AXUIElementCreateSystemWide
    except Exception:
        return None

    system = AXUIElementCreateSystemWide()
    return copy_ax_attribute(system, "AXFocusedUIElement")


def walk_ax_hierarchy(element, max_depth: int = 12) -> list[dict]:
    hierarchy = []
    current = element
    seen = set()

    for _ in range(max_depth):
        if current is None:
            break
        marker = id(current)
        if marker in seen:
            break
        seen.add(marker)

        node = read_ax_node(current)
        hierarchy.append(node)
        current = copy_ax_attribute(current, "AXParent")

    return hierarchy


def read_ax_node(element) -> dict[str, Any]:
    frame = copy_ax_attribute(element, "AXFrame")
    return {
        "role": _string_or_none(copy_ax_attribute(element, "AXRole")),
        "subrole": _string_or_none(copy_ax_attribute(element, "AXSubrole")),
        "title": _string_or_none(copy_ax_attribute(element, "AXTitle")),
        "description": _string_or_none(copy_ax_attribute(element, "AXDescription")),
        "identifier": _string_or_none(copy_ax_attribute(element, "AXIdentifier")),
        "value": _string_or_none(copy_ax_attribute(element, "AXValue")),
        "frame": _frame_value_to_dict(frame),
    }


def copy_ax_attribute(element, attribute: str):
    try:
        from ApplicationServices import AXUIElementCopyAttributeValue

        try:
            result = AXUIElementCopyAttributeValue(element, attribute, None)
        except TypeError:
            result = AXUIElementCopyAttributeValue(element, attribute)

        if isinstance(result, tuple):
            if len(result) >= 2 and result[0] == 0:
                return result[1]
            return None
        return result
    except Exception:
        return None


def _string_or_none(value) -> str | None:
    if value is None:
        return None
    if isinstance(value, str):
        return value
    return str(value)


def _frame_value_to_dict(value) -> dict | None:
    if isinstance(value, dict):
        return value
    if isinstance(value, AXFrame):
        return value.to_dict()
    if value is None:
        return None
    try:
        return {
            "x": float(value.origin.x),
            "y": float(value.origin.y),
            "width": float(value.size.width),
            "height": float(value.size.height),
        }
    except Exception:
        return None
