"""Strict local structured sources for post-send chat messages."""

from __future__ import annotations

from collections import deque
from dataclasses import dataclass
import logging
import threading
import time
from typing import Callable, Iterable

from .chat_bubble_capture import VisualBubbleSource
from .chat_window_capture import WindowFrame
from .kim_composer_capture import NormalizedRect, RecognizedLine
from .post_send_capture import (
    MAX_TRUSTED_SUBMISSION_CHARS,
    SendIntent,
    SourceResult,
)
from .wechat_composer_capture import WECHAT_BUNDLE_ID


logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class AXMessageNode:
    target_pid: int
    role: str
    text: str
    identity: str
    observed_at: float
    newly_observed: bool
    bounds: NormalizedRect
    secure: bool = False
    children: tuple[AXMessageNode, ...] = ()


class AccessibilityBubbleSource:
    def __init__(
        self,
        *,
        node_provider: Callable[[int], Iterable[AXMessageNode]] | None = None,
        clock: Callable[[], float] = time.monotonic,
        max_nodes: int = 128,
        traversal_timeout: float = 0.15,
    ):
        self._clock = clock
        self._max_nodes = max_nodes
        self._traversal_timeout = traversal_timeout
        self._native_provider = _NativeAXNodeProvider(clock=clock)
        self._node_provider = node_provider or self._native_provider
        self._cancelled = threading.Event()

    def read(self, intent: SendIntent) -> SourceResult:
        self._cancelled.clear()
        deadline = self._clock() + self._traversal_timeout
        try:
            roots = tuple(self._node_provider(intent.target_pid))
        except Exception:
            logger.exception("post-send AX tree read failed")
            return SourceResult.unavailable("ax_native_error")
        if not roots:
            return SourceResult.unavailable("ax_tree_unavailable")

        queue = deque(roots)
        failures: list[str] = []
        candidates: list[AXMessageNode] = []
        visited = 0
        while queue:
            if self._cancelled.is_set():
                return SourceResult.unavailable("ax_cancelled")
            if self._clock() > deadline:
                return SourceResult.unavailable("ax_traversal_timeout")
            if visited >= self._max_nodes:
                return SourceResult.unavailable("ax_traversal_limit")
            node = queue.popleft()
            visited += 1
            queue.extend(node.children)
            failure = self._failure_reason(intent, node)
            if failure is None:
                candidates.append(node)
            else:
                failures.append(failure)

        if not candidates:
            return SourceResult.unavailable(
                failures[-1] if failures else "ax_message_unavailable"
            )
        candidate = min(candidates, key=lambda node: node.bounds.y)
        source_prefix = (
            "wechat_postsend"
            if intent.bundle_id == WECHAT_BUNDLE_ID
            else "kim_postsend"
        )
        return SourceResult.success(
            candidate.text.strip(),
            f"{source_prefix}_ax",
            f"ax:{intent.target_pid}:{candidate.identity}",
            confidence=1.0,
            observed_at=candidate.observed_at,
            target_pid=intent.target_pid,
            stability_key=candidate.identity,
        )

    def cancel(self) -> None:
        self._cancelled.set()
        cancel = getattr(self._node_provider, "cancel", None)
        if callable(cancel):
            cancel()

    @staticmethod
    def _failure_reason(
        intent: SendIntent,
        node: AXMessageNode,
    ) -> str | None:
        if node.target_pid != intent.target_pid:
            return "ax_target_pid_mismatch"
        if node.secure:
            return "ax_secure_element"
        if node.role != "AXStaticText":
            return "ax_not_static_text"
        if not node.text.strip():
            return "ax_empty_text"
        if len(node.text.strip()) > MAX_TRUSTED_SUBMISSION_CHARS:
            return "ax_content_too_long"
        if not node.identity:
            return "ax_missing_identity"
        if node.observed_at < intent.submitted_at:
            return "ax_stale_node"
        if not node.newly_observed:
            return "ax_not_new"
        if node.bounds.x + node.bounds.width < 0.72:
            return "ax_not_outgoing"
        return None


class _NativeAXNodeProvider:
    """Bounded local AX snapshotter; native nodes are never guessed as new."""

    def __init__(self, *, clock: Callable[[], float], max_nodes: int = 128):
        self._clock = clock
        self._max_nodes = max_nodes
        self._cancelled = threading.Event()

    def cancel(self) -> None:
        self._cancelled.set()

    def __call__(self, target_pid: int) -> tuple[AXMessageNode, ...]:
        self._cancelled.clear()
        import ApplicationServices as AX

        application = AX.AXUIElementCreateApplication(target_pid)
        pending = deque([application])
        snapshots: list[AXMessageNode] = []
        visited = 0
        while pending and visited < self._max_nodes:
            if self._cancelled.is_set():
                break
            element = pending.popleft()
            visited += 1
            role = str(_ax_value(AX, element, "AXRole") or "")
            text = str(
                _ax_value(AX, element, "AXValue")
                or _ax_value(AX, element, "AXTitle")
                or ""
            )
            identity = str(_ax_value(AX, element, "AXIdentifier") or "")
            children = tuple(_ax_value(AX, element, "AXChildren") or ())
            pending.extend(children)
            snapshots.append(
                AXMessageNode(
                    target_pid=target_pid,
                    role=role,
                    text=text,
                    identity=identity,
                    observed_at=self._clock(),
                    newly_observed=False,
                    bounds=NormalizedRect(0.0, 0.0, 0.0, 0.0),
                    secure=role == "AXSecureTextField",
                )
            )
        return tuple(snapshots)


def _ax_value(ax_module, element, attribute):
    result = ax_module.AXUIElementCopyAttributeValue(element, attribute, None)
    if isinstance(result, tuple) and len(result) == 2:
        error, value = result
        if error != 0:
            return None
        return value
    return result


def default_message_sources(
    *,
    frame_provider: Callable[[int], WindowFrame | None],
    ax_node_provider: Callable[[int], Iterable[AXMessageNode]] | None = None,
    ocr_provider: Callable[
        [object, NormalizedRect], Iterable[RecognizedLine]
    ]
    | None = None,
    difference_provider: Callable[
        [object, object, NormalizedRect], Iterable[NormalizedRect]
    ]
    | None = None,
) -> tuple[AccessibilityBubbleSource, VisualBubbleSource]:
    return (
        AccessibilityBubbleSource(node_provider=ax_node_provider),
        VisualBubbleSource(
            frame_provider=frame_provider,
            ocr_provider=ocr_provider,
            difference_provider=difference_provider,
        ),
    )
