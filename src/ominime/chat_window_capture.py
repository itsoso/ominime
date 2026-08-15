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
        on_diagnostic: Callable[[str], None] | None = None,
        min_interval: float = BASELINE_MIN_INTERVAL_SECONDS,
    ):
        self._clock = clock
        self._window_provider = window_provider or self._native_windows
        self._image_provider = image_provider or self._native_window_image
        self._on_diagnostic = on_diagnostic or (lambda reason: None)
        self._min_interval = min_interval
        self._queue: queue.Queue[_CaptureRequest | object] = queue.Queue(
            maxsize=1
        )
        self._lock = threading.Lock()
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

    def take_baseline(self, target_pid: int) -> WindowFrame | None:
        with self._lock:
            baseline = self._baseline
            if baseline is None or baseline.target_pid != target_pid:
                return None
        try:
            current_window = self._select_window(target_pid)
        except Exception:
            logger.exception("chat window validation failed")
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
                    return
                request = item
                while request is not None:
                    frame = self._capture(request.target_pid)
                    with self._lock:
                        next_request = self._reschedule
                        self._reschedule = None
                        if not self._accepting:
                            next_request = None
                        if next_request is None:
                            self._baseline = frame if self._accepting else None
                            self._pending = False
                        else:
                            self._release_frame(frame)
                            frame = None
                    if next_request is None:
                        if frame is None and self._accepting:
                            self._safe_diagnostic("baseline_unavailable")
                        request = None
                    else:
                        request = next_request
            except Exception:
                logger.exception("unexpected baseline sampler worker failure")
                with self._lock:
                    self._baseline = None
                    self._pending = False
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
            return WindowFrame(
                image=image,
                window_id=window.window_id,
                target_pid=target_pid,
                width=window.width,
                height=window.height,
                captured_at=self._clock(),
            )
        except Exception:
            logger.exception("native chat window baseline capture failed")
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
            logger.exception("baseline diagnostic callback failed")

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
