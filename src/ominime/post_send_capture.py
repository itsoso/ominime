"""Contracts and orchestration primitives for post-send message capture."""

from __future__ import annotations

from dataclasses import dataclass, field, replace
from datetime import datetime
import logging
import queue
import threading
import time
from types import MappingProxyType
from typing import Callable, Mapping, Protocol, Sequence


MAX_TRUSTED_SUBMISSION_CHARS = 4000
DEFAULT_RETRY_DELAYS = (0.15, 0.35, 0.65, 1.0, 1.5, 2.0)
TASK_EXPIRY_GRACE_SECONDS = 0.05
DEFAULT_SOURCE_TIMEOUT_SECONDS = 0.2

logger = logging.getLogger(__name__)

# CPython cannot cancel a thread inside an arbitrary native AX/Vision call. A
# process-wide slot therefore caps a poisoned source worker at one: after a
# timeout, later coordinator lifecycles fail closed instead of accumulating
# stuck threads. Normal workers release the slot when they exit.
_SOURCE_WORKER_SLOT = threading.BoundedSemaphore(1)


@dataclass(frozen=True)
class SendIntent:
    intent_id: str
    submitted_at: float
    timestamp: datetime
    app_name: str
    bundle_id: str
    target_pid: int
    modifiers: Mapping[str, object]
    physical_key_count: int
    validation_text: str
    baseline: object | None

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "modifiers",
            MappingProxyType(dict(self.modifiers)),
        )


@dataclass(frozen=True)
class SourceResult:
    content: str = ""
    source: str | None = None
    message_identity: str | None = None
    confidence: float | None = None
    observed_at: float | None = None
    target_pid: int | None = None
    stability_key: str | None = None
    failure_reason: str | None = None
    diagnostics: tuple[str, ...] = ()

    @classmethod
    def success(
        cls,
        content: str,
        source: str,
        message_identity: str,
        *,
        confidence: float | None = None,
        observed_at: float | None = None,
        target_pid: int | None = None,
        stability_key: str | None = None,
    ) -> SourceResult:
        return cls(
            content=content,
            source=source,
            message_identity=message_identity,
            confidence=confidence,
            observed_at=observed_at,
            target_pid=target_pid,
            stability_key=stability_key,
        )

    @classmethod
    def unavailable(cls, failure_reason: str) -> SourceResult:
        return cls(failure_reason=failure_reason)


class MessageSource(Protocol):
    def read(self, intent: SendIntent) -> SourceResult: ...


class MessageSourceChain:
    def __init__(self, sources: Sequence[MessageSource]):
        self._sources = tuple(sources)

    def read(self, intent: SendIntent) -> SourceResult:
        diagnostics: list[str] = []
        last_failure = "post_send_source_unavailable"

        for source in self._sources:
            try:
                result = source.read(intent)
            except Exception:
                diagnostics.append(f"source_exception:{type(source).__name__}")
                last_failure = "source_exception"
                continue

            if result.failure_reason:
                last_failure = result.failure_reason
                diagnostics.extend(result.diagnostics)
                continue

            content = result.content.strip()
            rejection = self._rejection_reason(intent, result, content)
            if rejection:
                diagnostics.append(rejection)
                last_failure = rejection
                continue

            return replace(
                result,
                content=content,
                diagnostics=tuple(diagnostics) + result.diagnostics,
            )

        return SourceResult(
            failure_reason=last_failure,
            diagnostics=tuple(diagnostics),
        )

    @staticmethod
    def _rejection_reason(
        intent: SendIntent, result: SourceResult, content: str
    ) -> str | None:
        if not content:
            return "empty_content"
        if len(content) > MAX_TRUSTED_SUBMISSION_CHARS:
            return "content_too_long"
        if result.target_pid != intent.target_pid:
            return "target_pid_mismatch"
        if result.observed_at is None or result.observed_at < intent.submitted_at:
            return "stale_observation"
        if not result.source or not result.message_identity:
            return "missing_source_identity"
        return None


@dataclass(frozen=True)
class CaptureOutcome:
    intent_id: str
    content: str = ""
    source: str | None = None
    message_identity: str | None = None
    failure_reason: str | None = None
    diagnostics: tuple[str, ...] = ()


_STOP = object()


@dataclass
class _SourceReadRequest:
    intent: SendIntent
    completed: threading.Event = field(default_factory=threading.Event)
    result: SourceResult | None = None


class _BoundedSourceReader:
    """Run source calls on one fixed worker so a native hang is contained."""

    def __init__(self, source_chain: MessageSourceChain):
        self._source_chain = source_chain
        self._queue: queue.Queue[_SourceReadRequest | object] = queue.Queue(
            maxsize=1
        )
        self._lock = threading.Lock()
        self._poisoned = False
        self._stopping = False
        self._owns_slot = _SOURCE_WORKER_SLOT.acquire(blocking=False)
        self._worker: threading.Thread | None = None
        if not self._owns_slot:
            self._poisoned = True
            return
        self._worker = threading.Thread(
            target=self._run,
            name="ominime-post-send-source",
            daemon=True,
        )
        self._worker.start()

    def read(self, intent: SendIntent, timeout: float) -> SourceResult:
        with self._lock:
            if self._poisoned or self._stopping or self._worker is None:
                return SourceResult.unavailable("source_worker_unavailable")
            request = _SourceReadRequest(intent=intent)
            try:
                self._queue.put_nowait(request)
            except queue.Full:
                return SourceResult.unavailable("source_worker_busy")

        if not request.completed.wait(timeout):
            with self._lock:
                self._poisoned = True
            return SourceResult.unavailable("source_read_timeout")
        return request.result or SourceResult.unavailable("source_worker_exception")

    def stop(self) -> None:
        with self._lock:
            if self._stopping:
                return
            self._stopping = True
            if self._worker is None:
                return
            try:
                self._queue.put_nowait(_STOP)
            except queue.Full:
                return

    def _run(self) -> None:
        try:
            while True:
                item = self._queue.get()
                try:
                    if item is _STOP:
                        return
                    try:
                        item.result = self._source_chain.read(item.intent)
                    except Exception:
                        logger.exception(
                            "unexpected post-send source worker failure"
                        )
                        item.result = SourceResult.unavailable(
                            "source_worker_exception"
                        )
                    finally:
                        item.completed.set()
                    with self._lock:
                        if self._stopping:
                            return
                finally:
                    self._queue.task_done()
                    item = None
        finally:
            if self._owns_slot:
                self._owns_slot = False
                _SOURCE_WORKER_SLOT.release()


class PostSendCaptureCoordinator:
    """Run bounded post-send source reads away from the keyboard event path."""

    def __init__(
        self,
        source_chain: MessageSourceChain,
        *,
        on_success: Callable[[CaptureOutcome], None],
        on_diagnostic: Callable[[CaptureOutcome], None],
        clock: Callable[[], float] = time.monotonic,
        wait: Callable[[float], object] = time.sleep,
        max_queue_size: int = 64,
        retry_delays: Sequence[float] = DEFAULT_RETRY_DELAYS,
        source_timeout: float = DEFAULT_SOURCE_TIMEOUT_SECONDS,
    ):
        self._source_chain = source_chain
        self._source_reader = _BoundedSourceReader(source_chain)
        self._on_success = on_success
        self._on_diagnostic = on_diagnostic
        self._clock = clock
        self._wait = wait
        self._retry_delays = tuple(retry_delays)
        self._source_timeout = source_timeout
        self._queue: queue.Queue[SendIntent | object] = queue.Queue(
            maxsize=max_queue_size
        )
        self._deferred_diagnostics: queue.Queue[CaptureOutcome] = queue.Queue(
            maxsize=1
        )
        self._accepting = True
        self._stop_signaled = False
        self._state_lock = threading.Lock()
        self._worker = threading.Thread(
            target=self._run,
            name="ominime-post-send-capture",
            daemon=True,
        )
        self._worker.start()

    @property
    def worker_alive(self) -> bool:
        return self._worker.is_alive()

    def submit(self, intent: SendIntent) -> bool:
        with self._state_lock:
            if not self._accepting:
                self._release_baseline(intent)
                return False
            try:
                self._queue.put_nowait(intent)
            except queue.Full:
                self._release_baseline(intent)
                self._defer_diagnostic(
                    CaptureOutcome(
                        intent_id=intent.intent_id,
                        failure_reason="post_send_queue_full",
                    )
                )
                return False
        return True

    def stop(self, timeout: float = 3.0) -> None:
        with self._state_lock:
            if self._accepting:
                self._accepting = False
                self._discard_queued_intents()
            if not self._stop_signaled:
                self._queue.put_nowait(_STOP)
                self._stop_signaled = True
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.error("post-send coordinator worker did not stop within %.2fs", timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
                    self._source_reader.stop()
                    return
                self._capture(item)
            except Exception:
                intent_id = getattr(item, "intent_id", "unknown")
                logger.exception("unexpected post-send capture worker failure")
                self._safe_diagnostic(
                    CaptureOutcome(
                        intent_id=intent_id,
                        failure_reason="post_send_worker_exception",
                    )
                )
            finally:
                if isinstance(item, SendIntent):
                    self._release_baseline(item)
                self._queue.task_done()
                item = None
                self._drain_deferred_diagnostics()

    def _capture(self, intent: SendIntent) -> None:
        previous_ocr_state: tuple[str, str] | None = None
        last_result = SourceResult.unavailable("capture_timeout")
        deadline = (
            intent.submitted_at
            + max(self._retry_delays, default=0.0)
            + TASK_EXPIRY_GRACE_SECONDS
        )

        for relative_delay in self._retry_delays:
            if self._clock() > deadline:
                self._report_expired(intent)
                return
            remaining = intent.submitted_at + relative_delay - self._clock()
            if remaining > 0:
                self._wait(remaining)
            if self._clock() > deadline:
                self._report_expired(intent)
                return

            read_timeout = min(
                self._source_timeout,
                max(0.0, deadline - self._clock()),
            )
            if read_timeout <= 0:
                self._report_expired(intent)
                return
            last_result = self._source_reader.read(intent, read_timeout)
            if self._clock() > deadline:
                self._report_expired(intent)
                return
            if last_result.failure_reason == "source_read_timeout":
                self._safe_diagnostic(
                    CaptureOutcome(
                        intent_id=intent.intent_id,
                        failure_reason="source_read_timeout",
                    )
                )
                return
            if last_result.failure_reason:
                previous_ocr_state = None
                continue

            if not self._is_ocr(last_result):
                self._safe_success(self._success_outcome(intent, last_result))
                return

            if last_result.stability_key is None:
                previous_ocr_state = None
                continue
            current_ocr_state = (
                last_result.content,
                last_result.stability_key,
            )
            if previous_ocr_state == current_ocr_state:
                self._safe_success(self._success_outcome(intent, last_result))
                return
            previous_ocr_state = current_ocr_state

        self._safe_diagnostic(
            CaptureOutcome(
                intent_id=intent.intent_id,
                failure_reason=last_result.failure_reason or "ocr_unstable",
                diagnostics=last_result.diagnostics,
            )
        )

    def _report_expired(self, intent: SendIntent) -> None:
        self._safe_diagnostic(
            CaptureOutcome(
                intent_id=intent.intent_id,
                failure_reason="capture_expired",
            )
        )

    @staticmethod
    def _is_ocr(result: SourceResult) -> bool:
        return bool(result.source and result.source.endswith("_ocr"))

    @staticmethod
    def _success_outcome(
        intent: SendIntent, result: SourceResult
    ) -> CaptureOutcome:
        return CaptureOutcome(
            intent_id=intent.intent_id,
            content=result.content,
            source=result.source,
            message_identity=result.message_identity,
            diagnostics=result.diagnostics,
        )

    def _safe_success(self, outcome: CaptureOutcome) -> None:
        try:
            self._on_success(outcome)
        except Exception:
            logger.exception("post-send success callback failed")

    def _safe_diagnostic(self, outcome: CaptureOutcome) -> None:
        try:
            self._on_diagnostic(outcome)
        except Exception:
            logger.exception("post-send diagnostic callback failed")

    def _drain_deferred_diagnostics(self) -> None:
        while True:
            try:
                outcome = self._deferred_diagnostics.get_nowait()
            except queue.Empty:
                return
            self._safe_diagnostic(outcome)

    def _defer_diagnostic(self, outcome: CaptureOutcome) -> bool:
        try:
            self._deferred_diagnostics.put_nowait(outcome)
        except queue.Full:
            return False
        return True

    def _discard_queued_intents(self) -> None:
        while True:
            try:
                item = self._queue.get_nowait()
            except queue.Empty:
                return
            try:
                if isinstance(item, SendIntent):
                    self._release_baseline(item)
                    self._defer_diagnostic(
                        CaptureOutcome(
                            intent_id=item.intent_id,
                            failure_reason="post_send_shutdown",
                        )
                    )
            finally:
                self._queue.task_done()
                item = None

    def _release_baseline(self, intent: SendIntent) -> None:
        baseline = intent.baseline
        release = getattr(baseline, "release", None)
        if not callable(release):
            return
        try:
            release()
        except Exception:
            logger.exception("post-send baseline release failed")
            self._safe_diagnostic(
                CaptureOutcome(
                    intent_id=intent.intent_id,
                    failure_reason="baseline_release_failed",
                )
            )
