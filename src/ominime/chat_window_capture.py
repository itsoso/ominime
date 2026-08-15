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
        self._queue: queue.Queue[int | object] = queue.Queue(maxsize=1)
        self._lock = threading.Lock()
        self._accepting = True
        self._pending = False
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
            if not self._accepting or self._pending:
                return False
            if (
                self._last_scheduled_pid == target_pid
                and self._last_scheduled_at is not None
                and now - self._last_scheduled_at < self._min_interval
            ):
                return False
            self._baseline = None
            try:
                self._queue.put_nowait(target_pid)
            except queue.Full:
                return False
            self._pending = True
            self._last_scheduled_pid = target_pid
            self._last_scheduled_at = now
            return True

    def take_baseline(self, target_pid: int) -> WindowFrame | None:
        with self._lock:
            if (
                self._baseline is None
                or self._baseline.target_pid != target_pid
            ):
                return None
            baseline = self._baseline
            self._baseline = None
            return baseline

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
            self._baseline = None

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            frame = None
            try:
                if item is _STOP:
                    with self._lock:
                        self._baseline = None
                        self._pending = False
                    return
                frame = self._capture(item)
                with self._lock:
                    self._baseline = frame
                    self._pending = False
                if frame is None:
                    self._safe_diagnostic("baseline_unavailable")
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

    def _capture(self, target_pid: int) -> WindowFrame | None:
        try:
            window = next(
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
