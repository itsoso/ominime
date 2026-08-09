"""Capture and model trusted Doubao input-method candidate selections."""

import time
from collections import deque
from dataclasses import dataclass
from typing import Callable, Iterable


DOUBAO_BUNDLE_ID = "com.bytedance.inputmethod.doubaoime"
SUPPORTED_TARGET_BUNDLE_IDS = frozenset({"Kem", "com.tencent.xinWeChat"})
COMPOSER_TOP_FRACTION = 0.55
MAX_COMPOSED_CHARS = 4000
NUMBER_KEYCODE_TO_INDEX = {
    18: 0,
    19: 1,
    20: 2,
    21: 3,
    23: 4,
    22: 5,
    26: 6,
    28: 7,
    25: 8,
}


@dataclass(frozen=True)
class Rect:
    x: float
    y: float
    width: float
    height: float


@dataclass(frozen=True)
class CandidateSnapshot:
    candidates: tuple[str, ...]
    target_pid: int
    captured_at: float


@dataclass(frozen=True)
class WindowRecord:
    pid: int
    bounds: Rect


@dataclass(frozen=True)
class CompositionResult:
    candidate_committed: bool = False
    committed_text: str = ""


def candidate_is_in_composer(candidate: Rect, target: Rect) -> bool:
    """Return whether a candidate window is anchored in the target composer."""
    if min(candidate.width, candidate.height, target.width, target.height) <= 0:
        return False
    if candidate.width > target.width or candidate.height > target.height * 0.25:
        return False
    center_x = candidate.x + candidate.width / 2
    center_y = candidate.y + candidate.height / 2
    return (
        target.x <= center_x <= target.x + target.width
        and target.y + target.height * COMPOSER_TOP_FRACTION
        <= center_y
        <= target.y + target.height
    )


def rect_from_window_bounds(bounds) -> Rect | None:
    """Convert Python or Objective-C window-bound mappings to a Rect."""
    getter = getattr(bounds, "get", None)
    if getter is None:
        return None
    try:
        return Rect(
            x=float(getter("X", getter("x"))),
            y=float(getter("Y", getter("y"))),
            width=float(getter("Width", getter("width"))),
            height=float(getter("Height", getter("height"))),
        )
    except (TypeError, ValueError):
        return None


def collect_static_text_values(
    roots: Iterable[object],
    attribute_reader: Callable[[object, str], object],
    *,
    max_nodes: int = 200,
) -> tuple[str, ...]:
    """Collect bounded candidate strings from an Accessibility subtree."""
    pending = deque(roots)
    visited: set[int] = set()
    values: list[str] = []
    seen_values: set[str] = set()
    processed = 0
    while pending and processed < max_nodes:
        node = pending.popleft()
        identity = id(node)
        if identity in visited:
            continue
        visited.add(identity)
        processed += 1
        if attribute_reader(node, "AXRole") == "AXStaticText":
            value = attribute_reader(node, "AXValue")
            if isinstance(value, str):
                value = value.strip()
                if value and value not in seen_values:
                    values.append(value)
                    seen_values.add(value)
        children = attribute_reader(node, "AXChildren")
        if isinstance(children, (list, tuple)):
            pending.extend(children)
    return tuple(values)


class DoubaoCandidateReader:
    """Read candidates only when Doubao is anchored to a supported composer."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        process_provider: Callable[[], Iterable[tuple[str, int]]] | None = None,
        ax_roots_provider: Callable[[int], Iterable[object]] | None = None,
        window_provider: Callable[[], Iterable[WindowRecord]] | None = None,
        attribute_reader: Callable[[object, str], object] | None = None,
    ):
        self._clock = clock
        self._process_provider = process_provider or self._native_processes
        self._ax_roots_provider = ax_roots_provider or self._native_ax_roots
        self._window_provider = window_provider or self._native_windows
        self._attribute_reader = attribute_reader or self._native_ax_attribute

    def read(
        self,
        *,
        target_pid: int,
        target_bundle_id: str,
    ) -> CandidateSnapshot | None:
        if target_pid <= 0 or target_bundle_id not in SUPPORTED_TARGET_BUNDLE_IDS:
            return None
        try:
            doubao_pid = next(
                (
                    int(pid)
                    for bundle_id, pid in self._process_provider()
                    if bundle_id == DOUBAO_BUNDLE_ID and int(pid) > 0
                ),
                0,
            )
            if doubao_pid <= 0:
                return None
            candidates = collect_static_text_values(
                self._ax_roots_provider(doubao_pid),
                self._attribute_reader,
            )
            if not candidates:
                return None
            windows = tuple(self._window_provider())
            candidate_windows = (
                window.bounds for window in windows if window.pid == doubao_pid
            )
            target_windows = tuple(
                window.bounds for window in windows if window.pid == target_pid
            )
            if not target_windows or not any(
                candidate_is_in_composer(candidate, target)
                for candidate in candidate_windows
                for target in target_windows
            ):
                return None
            return CandidateSnapshot(candidates, target_pid, self._clock())
        except Exception:
            return None

    @staticmethod
    def _native_processes() -> Iterable[tuple[str, int]]:
        from AppKit import NSWorkspace

        workspace = NSWorkspace.sharedWorkspace()
        return tuple(
            (application.bundleIdentifier() or "", int(application.processIdentifier()))
            for application in workspace.runningApplications()
        )

    @staticmethod
    def _native_ax_attribute(element, attribute: str):
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

    def _native_ax_roots(self, pid: int) -> Iterable[object]:
        from ApplicationServices import AXUIElementCreateApplication

        application = AXUIElementCreateApplication(pid)
        windows = self._native_ax_attribute(application, "AXWindows")
        if isinstance(windows, (list, tuple)) and windows:
            return tuple(windows)
        return (application,)

    @staticmethod
    def _native_windows() -> Iterable[WindowRecord]:
        import Quartz

        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        window_info = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        records: list[WindowRecord] = []
        for item in window_info or ():
            pid = int(item.get(Quartz.kCGWindowOwnerPID, 0) or 0)
            bounds = item.get(Quartz.kCGWindowBounds) or {}
            rect = rect_from_window_bounds(bounds)
            if rect is None:
                continue
            if pid > 0 and rect.width > 0 and rect.height > 0:
                records.append(WindowRecord(pid=pid, bounds=rect))
        return tuple(records)


class DoubaoCompositionState:
    """Pure, expiring state for one target application's Doubao composition."""

    def __init__(
        self,
        *,
        timeout_seconds: float,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.timeout_seconds = timeout_seconds
        self._clock = clock
        self.clear()

    @property
    def has_active_candidate(self) -> bool:
        return bool(self._candidates)

    @property
    def selected_index(self) -> int:
        return self._selected_index

    @property
    def pending_preedit(self) -> str:
        return self._pending_preedit

    @property
    def confirmed_text(self) -> str:
        return self._confirmed_text

    def clear(self):
        self._target_pid = 0
        self._updated_at = 0.0
        self._candidates: tuple[str, ...] = ()
        self._selected_index = 0
        self._pending_preedit = ""
        self._confirmed_text = ""
        self._composer_trusted = False

    def _prepare(self, target_pid: int) -> bool:
        if target_pid <= 0:
            self.clear()
            return False
        now = self._clock()
        expired = (
            self._updated_at > 0
            and now - self._updated_at > self.timeout_seconds
        )
        if expired or (self._target_pid > 0 and self._target_pid != target_pid):
            self.clear()
        if self._target_pid == 0:
            self._target_pid = target_pid
        self._updated_at = now
        return True

    def _append_confirmed(self, text: str):
        if not text:
            return
        available = MAX_COMPOSED_CHARS - len(self._confirmed_text)
        if available > 0:
            self._confirmed_text += text[:available]

    def record_printable(self, text: str, *, target_pid: int):
        if not self._prepare(target_pid):
            return
        printable = "".join(character for character in text if character.isprintable())
        if printable:
            available = MAX_COMPOSED_CHARS - len(self._pending_preedit)
            self._pending_preedit += printable[:available]

    def update_candidates(
        self,
        snapshot: CandidateSnapshot | None,
        *,
        target_pid: int,
    ):
        if not self._prepare(target_pid):
            return
        if snapshot is None:
            self._candidates = ()
            self._selected_index = 0
            if self._composer_trusted and self._pending_preedit:
                self._append_confirmed(self._pending_preedit)
                self._pending_preedit = ""
            return
        if snapshot.target_pid != target_pid:
            self.clear()
            return
        candidates = tuple(
            dict.fromkeys(
                value.strip()
                for value in snapshot.candidates
                if isinstance(value, str) and value.strip()
            )
        )
        if not candidates:
            self.update_candidates(None, target_pid=target_pid)
            return
        if candidates != self._candidates:
            self._selected_index = 0
        self._candidates = candidates
        self._composer_trusted = True

    def _commit_candidate(self, index: int) -> CompositionResult:
        if not self._candidates:
            return CompositionResult()
        selected_index = min(max(index, 0), len(self._candidates) - 1)
        selected = self._candidates[selected_index]
        self._append_confirmed(selected)
        self._candidates = ()
        self._selected_index = 0
        self._pending_preedit = ""
        return CompositionResult(candidate_committed=True, committed_text=selected)

    def handle_key(self, *, keycode: int, text: str, target_pid: int) -> CompositionResult:
        if not self._prepare(target_pid):
            return CompositionResult()
        if keycode == 51:  # Backspace
            if self._pending_preedit:
                self._pending_preedit = self._pending_preedit[:-1]
            elif self._confirmed_text:
                self._confirmed_text = self._confirmed_text[:-1]
            return CompositionResult()
        if keycode == 123 and self._candidates:  # Left
            self._selected_index = max(0, self._selected_index - 1)
            return CompositionResult()
        if keycode == 124 and self._candidates:  # Right
            self._selected_index = min(
                len(self._candidates) - 1,
                self._selected_index + 1,
            )
            return CompositionResult()
        if self._candidates and keycode in NUMBER_KEYCODE_TO_INDEX:
            return self._commit_candidate(NUMBER_KEYCODE_TO_INDEX[keycode])
        if self._candidates and keycode in (36, 49):  # Enter or Space
            return self._commit_candidate(self._selected_index)
        if not self._candidates and self._composer_trusted:
            if keycode == 49:
                self._append_confirmed(" ")
            elif keycode in NUMBER_KEYCODE_TO_INDEX:
                self._append_confirmed(text)
        return CompositionResult()

    def pop_submission(self, *, target_pid: int) -> str:
        if not self._prepare(target_pid) or self._candidates:
            return ""
        content = self._confirmed_text
        self.clear()
        return content
