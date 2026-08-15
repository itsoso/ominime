"""Contracts and orchestration primitives for post-send message capture."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from typing import Protocol, Sequence


MAX_TRUSTED_SUBMISSION_CHARS = 4000


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
