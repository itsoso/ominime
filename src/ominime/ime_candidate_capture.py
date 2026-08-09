"""Capture and model trusted Doubao input-method candidate selections."""

import time
from dataclasses import dataclass
from typing import Callable


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
class CompositionResult:
    candidate_committed: bool = False
    committed_text: str = ""


def candidate_is_in_composer(candidate: Rect, target: Rect) -> bool:
    """Return whether a candidate window is anchored in the target composer."""
    if min(candidate.width, candidate.height, target.width, target.height) <= 0:
        return False
    center_x = candidate.x + candidate.width / 2
    center_y = candidate.y + candidate.height / 2
    return (
        target.x <= center_x <= target.x + target.width
        and target.y + target.height * COMPOSER_TOP_FRACTION
        <= center_y
        <= target.y + target.height
    )


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
