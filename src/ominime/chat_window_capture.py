"""In-memory chat window baselines captured outside the EventTap callback."""

from __future__ import annotations

from dataclasses import dataclass
import logging
import queue
import threading
import time
from typing import Callable, Iterable


MIN_CHAT_WINDOW_WIDTH = 300
MIN_CHAT_WINDOW_HEIGHT = 200
BASELINE_MIN_INTERVAL_SECONDS = 0.25

logger = logging.getLogger(__name__)

SESSION_ANCHOR_PREFIX = "v1:"
SESSION_ANCHOR_MAX_HAMMING_DISTANCE = 12


def session_anchors_match(first: str | None, second: str | None) -> bool:
    if not first or not second:
        return False
    if not (
        first.startswith(SESSION_ANCHOR_PREFIX)
        and second.startswith(SESSION_ANCHOR_PREFIX)
    ):
        return first == second
    expected_length = len(SESSION_ANCHOR_PREFIX) + 64
    if len(first) != expected_length or len(second) != expected_length:
        return False
    try:
        left = int(first[len(SESSION_ANCHOR_PREFIX) :], 16)
        right = int(second[len(SESSION_ANCHOR_PREFIX) :], 16)
    except ValueError:
        return False
    return (left ^ right).bit_count() <= SESSION_ANCHOR_MAX_HAMMING_DISTANCE


def _perceptual_session_anchor(
    data: bytes,
    width: int,
    height: int,
    row_bytes: int,
    pixel_bytes: int,
) -> str:
    """Hash title-region edge directions, ignoring uniform color shifts."""
    x0 = int(width * 0.34)
    x1 = max(x0 + 2, int(width * 0.68))
    y0 = int(height * 0.04)
    y1 = max(y0 + 1, int(height * 0.10))
    columns = 33
    rows = 8

    def gray(x: int, y: int) -> int:
        offset = y * row_bytes + x * pixel_bytes
        pixel = data[offset : offset + min(3, pixel_bytes)]
        return sum(pixel) // max(1, len(pixel))

    samples: list[list[int]] = []
    for row in range(rows):
        y = min(height - 1, y0 + ((y1 - y0 - 1) * row // max(1, rows - 1)))
        samples.append(
            [
                gray(
                    min(
                        width - 1,
                        x0 + ((x1 - x0 - 1) * column // (columns - 1)),
                    ),
                    y,
                )
                for column in range(columns)
            ]
        )
    signature = 0
    for row in samples:
        for left, right in zip(row, row[1:]):
            signature = (signature << 1) | int(left > right)
    return f"{SESSION_ANCHOR_PREFIX}{signature:064x}"


@dataclass(frozen=True)
class WindowInfo:
    window_id: int
    pid: int
    layer: int
    width: float
    height: float


@dataclass(frozen=True)
class WindowFrame:
    image: object | None
    window_id: int
    target_pid: int
    width: float
    height: float
    captured_at: float
    session_anchor: str | None = None

    def release(self) -> None:
        object.__setattr__(self, "image", None)


_STOP = object()


@dataclass(frozen=True)
class _CaptureRequest:
    target_pid: int
    generation: int


class ChatWindowBaselineSampler:
    """Coalesce typing activity into one recent in-memory window frame."""

    def __init__(
        self,
        *,
        clock: Callable[[], float] = time.monotonic,
        window_provider: Callable[[], Iterable[WindowInfo]] | None = None,
        image_provider: Callable[[int], object] | None = None,
        anchor_provider: Callable[[object, float, float], str | None]
        | None = None,
        on_diagnostic: Callable[[str], None] | None = None,
        min_interval: float = BASELINE_MIN_INTERVAL_SECONDS,
    ):
        self._clock = clock
        self._window_provider = window_provider or self._native_windows
        self._image_provider = image_provider or self._native_window_image
        self._anchor_provider = anchor_provider or self._native_session_anchor
        self._on_diagnostic = on_diagnostic or (lambda reason: None)
        self._min_interval = min_interval
        self._queue: queue.Queue[_CaptureRequest | object] = queue.Queue(
            maxsize=1
        )
        self._lock = threading.Lock()
        self._condition = threading.Condition(self._lock)
        self._accepting = True
        self._pending = False
        self._generation = 0
        self._reschedule: _CaptureRequest | None = None
        self._last_scheduled_pid: int | None = None
        self._last_scheduled_at: float | None = None
        self._baseline: WindowFrame | None = None
        self._worker = threading.Thread(
            target=self._run,
            name="ominime-chat-window-baseline",
            daemon=True,
        )
        self._worker.start()

    @property
    def worker_alive(self) -> bool:
        return self._worker.is_alive()

    @property
    def has_baseline(self) -> bool:
        with self._lock:
            return self._baseline is not None

    def schedule(self, target_pid: int) -> bool:
        if target_pid <= 0:
            return False
        now = self._clock()
        with self._lock:
            if not self._accepting:
                return False
            if (
                self._last_scheduled_pid == target_pid
                and self._last_scheduled_at is not None
                and now - self._last_scheduled_at < self._min_interval
            ):
                return False
            self._generation += 1
            request = _CaptureRequest(target_pid, self._generation)
            self._release_frame(self._baseline)
            self._baseline = None
            self._last_scheduled_pid = target_pid
            self._last_scheduled_at = now
            if self._pending:
                self._reschedule = request
                return True
            try:
                self._queue.put_nowait(request)
            except queue.Full:
                return False
            self._pending = True
            return True

    def take_baseline(
        self, target_pid: int, *, wait_timeout: float = 0.0
    ) -> WindowFrame | None:
        deadline = time.monotonic() + max(0.0, wait_timeout)
        with self._condition:
            while self._baseline is None and self._pending:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    break
                self._condition.wait(remaining)
            baseline = self._baseline
            if baseline is None or baseline.target_pid != target_pid:
                return None
        try:
            current_window = self._select_window(target_pid)
        except Exception:
            logger.error("chat window validation failed")
            current_window = None
        with self._lock:
            if (
                self._baseline is not baseline
                or current_window is None
                or baseline.window_id != current_window.window_id
            ):
                if self._baseline is baseline:
                    self._release_frame(baseline)
                    self._baseline = None
                return None
            self._baseline = None
            return baseline

    def capture_current_frame(self, target_pid: int) -> WindowFrame | None:
        """Synchronously capture a current frame from a non-EventTap worker."""
        return self._capture(target_pid)

    def stop(self, timeout: float = 1.0) -> None:
        with self._lock:
            if not self._accepting:
                return
            self._accepting = False
        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            logger.error("baseline sampler stop timed out while queue was full")
            return
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.error("baseline sampler worker did not stop within %.2fs", timeout)
            return
        with self._lock:
            self._release_frame(self._baseline)
            self._baseline = None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            frame = None
            try:
                if item is _STOP:
                    with self._lock:
                        self._release_frame(self._baseline)
                        self._baseline = None
                        self._pending = False
                        self._reschedule = None
                        self._condition.notify_all()
                    return
                request = item
                while request is not None:
                    frame = self._capture(request.target_pid)
                    frame_available = False
                    with self._lock:
                        next_request = self._reschedule
                        self._reschedule = None
                        if not self._accepting:
                            next_request = None
                        if next_request is None:
                            if self._accepting:
                                self._baseline = frame
                                frame_available = frame is not None
                            else:
                                self._release_frame(frame)
                                self._baseline = None
                            frame = None
                            self._pending = False
                            self._condition.notify_all()
                        else:
                            self._release_frame(frame)
                            frame = None
                    if next_request is None:
                        if not frame_available and self._accepting:
                            self._safe_diagnostic("baseline_unavailable")
                        request = None
                    else:
                        request = next_request
            except Exception:
                logger.error("unexpected baseline sampler worker failure")
                with self._lock:
                    self._baseline = None
                    self._pending = False
                    self._condition.notify_all()
                self._safe_diagnostic("baseline_unavailable")
            finally:
                self._queue.task_done()
                frame = None
                item = None

    @staticmethod
    def _release_frame(frame: WindowFrame | None) -> None:
        if frame is not None:
            frame.release()

    def _capture(self, target_pid: int) -> WindowFrame | None:
        try:
            window = self._select_window(target_pid)
            if window is None:
                return None
            image = self._image_provider(window.window_id)
            if image is None:
                return None
            try:
                session_anchor = self._anchor_provider(
                    image, window.width, window.height
                )
            except Exception:
                logger.error("chat window session anchor unavailable")
                session_anchor = None
            return WindowFrame(
                image=image,
                window_id=window.window_id,
                target_pid=target_pid,
                width=window.width,
                height=window.height,
                captured_at=self._clock(),
                session_anchor=session_anchor,
            )
        except Exception:
            logger.error("native chat window baseline capture failed")
            return None

    def _select_window(self, target_pid: int) -> WindowInfo | None:
        return next(
            (
                candidate
                for candidate in self._window_provider()
                if candidate.pid == target_pid
                and candidate.layer == 0
                and candidate.width >= MIN_CHAT_WINDOW_WIDTH
                and candidate.height >= MIN_CHAT_WINDOW_HEIGHT
            ),
            None,
        )

    def _safe_diagnostic(self, reason: str) -> None:
        try:
            self._on_diagnostic(reason)
        except Exception:
            logger.error("baseline diagnostic callback failed")

    @staticmethod
    def _native_windows() -> tuple[WindowInfo, ...]:
        import Quartz

        options = (
            Quartz.kCGWindowListOptionOnScreenOnly
            | Quartz.kCGWindowListExcludeDesktopElements
        )
        items = Quartz.CGWindowListCopyWindowInfo(options, Quartz.kCGNullWindowID)
        windows = []
        for item in items or ():
            bounds = item.get(Quartz.kCGWindowBounds) or {}
            try:
                windows.append(
                    WindowInfo(
                        window_id=int(item.get(Quartz.kCGWindowNumber, 0) or 0),
                        pid=int(item.get(Quartz.kCGWindowOwnerPID, 0) or 0),
                        layer=int(item.get(Quartz.kCGWindowLayer, 0) or 0),
                        width=float(bounds.get("Width", 0) or 0),
                        height=float(bounds.get("Height", 0) or 0),
                    )
                )
            except (TypeError, ValueError):
                continue
        return tuple(windows)

    @staticmethod
    def _native_window_image(window_id: int):
        import Quartz

        return Quartz.CGWindowListCreateImageFromArray(
            Quartz.CGRectNull,
            [window_id],
            Quartz.kCGWindowImageBoundsIgnoreFraming,
        )

    @staticmethod
    def _native_session_anchor(
        image: object, window_width: float, window_height: float
    ) -> str | None:
        """Hash stable header pixels; never retain or serialize their contents."""
        import Quartz

        width = int(Quartz.CGImageGetWidth(image))
        height = int(Quartz.CGImageGetHeight(image))
        if width <= 0 or height <= 0 or window_width <= 0 or window_height <= 0:
            return None
        data = bytes(
            Quartz.CGDataProviderCopyData(Quartz.CGImageGetDataProvider(image))
        )
        row_bytes = int(Quartz.CGImageGetBytesPerRow(image))
        pixel_bytes = max(1, int(Quartz.CGImageGetBitsPerPixel(image)) // 8)
        return _perceptual_session_anchor(
            data,
            width,
            height,
            row_bytes,
            pixel_bytes,
        )
