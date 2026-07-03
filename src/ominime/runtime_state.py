"""Process-local runtime state shared by the menu bar app and web API."""

from dataclasses import dataclass
from datetime import datetime
from threading import Lock
from typing import Optional


@dataclass(frozen=True)
class RuntimeState:
    recording_status: str = "unknown"
    status_updated_at: Optional[datetime] = None
    listener_started_at: Optional[datetime] = None
    last_error: Optional[str] = None

    @property
    def is_recording(self) -> bool:
        return self.recording_status == "recording"


_lock = Lock()
_state = RuntimeState()


def get_runtime_state() -> RuntimeState:
    with _lock:
        return _state


def set_recording_status(status: str, *, error: Optional[str] = None) -> RuntimeState:
    global _state
    now = datetime.now()

    with _lock:
        listener_started_at = _state.listener_started_at
        if status == "recording" and listener_started_at is None:
            listener_started_at = now

        _state = RuntimeState(
            recording_status=status,
            status_updated_at=now,
            listener_started_at=listener_started_at,
            last_error=error,
        )
        return _state


def reset_runtime_state() -> RuntimeState:
    global _state
    with _lock:
        _state = RuntimeState()
        return _state
