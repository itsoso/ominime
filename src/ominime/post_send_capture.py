"""Contracts and orchestration primitives for post-send message capture."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
import logging
import queue
import threading
import time
from typing import Callable, Protocol, Sequence


MAX_TRUSTED_SUBMISSION_CHARS = 4000
DEFAULT_RETRY_DELAYS = (0.15, 0.35, 0.65, 1.0, 1.5, 2.0)

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SendIntent:
    intent_id: str
    submitted_at: float
    timestamp: datetime
    app_name: str
    bundle_id: str
    target_pid: int
    modifiers: dict
    physical_key_count: int
    validation_text: str
    baseline: object | None


@dataclass(frozen=True)
class SourceResult:
    content: str = ""
    source: str | None = None
    message_identity: str | None = None
    confidence: float | None = None
    observed_at: float | None = None
    target_pid: int | None = None
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
    ) -> SourceResult:
        return cls(
            content=content,
            source=source,
            message_identity=message_identity,
            confidence=confidence,
            observed_at=observed_at,
            target_pid=target_pid,
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
    ):
        self._source_chain = source_chain
        self._on_success = on_success
        self._on_diagnostic = on_diagnostic
        self._clock = clock
        self._wait = wait
        self._retry_delays = tuple(retry_delays)
        self._queue: queue.Queue[SendIntent | object] = queue.Queue(
            maxsize=max_queue_size
        )
        self._accepting = True
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
                return False
            try:
                self._queue.put_nowait(intent)
            except queue.Full:
                self._safe_diagnostic(
                    CaptureOutcome(
                        intent_id=intent.intent_id,
                        failure_reason="post_send_queue_full",
                    )
                )
                return False
        return True

    def stop(self, timeout: float = 3.0) -> None:
        with self._state_lock:
            if not self._accepting:
                return
            self._accepting = False

        try:
            self._queue.put(_STOP, timeout=timeout)
        except queue.Full:
            logger.error("post-send coordinator stop timed out while queue was full")
            return
        self._worker.join(timeout=timeout)
        if self._worker.is_alive():
            logger.error("post-send coordinator worker did not stop within %.2fs", timeout)

    def _run(self) -> None:
        while True:
            item = self._queue.get()
            try:
                if item is _STOP:
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

    def _capture(self, intent: SendIntent) -> None:
        previous_ocr_text: str | None = None
        last_result = SourceResult.unavailable("capture_timeout")

        for relative_delay in self._retry_delays:
            remaining = intent.submitted_at + relative_delay - self._clock()
            if remaining > 0:
                self._wait(remaining)

            last_result = self._source_chain.read(intent)
            if last_result.failure_reason:
                previous_ocr_text = None
                continue

            if not self._is_ocr(last_result):
                self._safe_success(self._success_outcome(intent, last_result))
                return

            if previous_ocr_text == last_result.content:
                self._safe_success(self._success_outcome(intent, last_result))
                return
            previous_ocr_text = last_result.content

        self._safe_diagnostic(
            CaptureOutcome(
                intent_id=intent.intent_id,
                failure_reason=last_result.failure_reason or "ocr_unstable",
                diagnostics=last_result.diagnostics,
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
