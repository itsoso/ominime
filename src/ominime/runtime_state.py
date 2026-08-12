"""Cross-process recording state shared by the menu bar app and web API."""

from dataclasses import asdict, dataclass, replace
from datetime import datetime, timezone
import json
import os
from pathlib import Path
from threading import Lock, get_ident
from typing import Optional

from .config import config


RUNTIME_HEARTBEAT_TTL_SECONDS = 90
_state_file_path = config.data_dir / "runtime-state.json"


@dataclass(frozen=True)
class RuntimeState:
    recording_status: str = "unknown"
    status_updated_at: Optional[datetime] = None
    listener_started_at: Optional[datetime] = None
    heartbeat_at: Optional[datetime] = None
    process_id: Optional[int] = None
    last_error: Optional[str] = None

    @property
    def is_recording(self) -> bool:
        return self.recording_status == "recording"


_lock = Lock()
_state = RuntimeState()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _serialize_datetime(value: Optional[datetime]) -> Optional[str]:
    return value.isoformat() if value is not None else None


def _parse_datetime(value) -> Optional[datetime]:
    if not isinstance(value, str) or not value:
        return None
    parsed = datetime.fromisoformat(value)
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _state_to_dict(state: RuntimeState) -> dict:
    payload = asdict(state)
    for key in ("status_updated_at", "listener_started_at", "heartbeat_at"):
        payload[key] = _serialize_datetime(payload[key])
    return payload


def _state_from_dict(payload: dict) -> RuntimeState:
    return RuntimeState(
        recording_status=str(payload.get("recording_status") or "unknown"),
        status_updated_at=_parse_datetime(payload.get("status_updated_at")),
        listener_started_at=_parse_datetime(payload.get("listener_started_at")),
        heartbeat_at=_parse_datetime(payload.get("heartbeat_at")),
        process_id=(
            int(payload["process_id"])
            if isinstance(payload.get("process_id"), int)
            else None
        ),
        last_error=(str(payload["last_error"]) if payload.get("last_error") else None),
    )


def _read_shared_state() -> Optional[RuntimeState]:
    try:
        payload = json.loads(_state_file_path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return None
    except (OSError, UnicodeError, json.JSONDecodeError):
        return RuntimeState(last_error="runtime_state_unreadable")
    if not isinstance(payload, dict):
        return RuntimeState(last_error="runtime_state_unreadable")
    try:
        return _state_from_dict(payload)
    except (TypeError, ValueError):
        return RuntimeState(last_error="runtime_state_unreadable")


def _write_shared_state(state: RuntimeState) -> None:
    _state_file_path.parent.mkdir(parents=True, exist_ok=True)
    _state_file_path.parent.chmod(0o700)
    temporary_path = _state_file_path.with_name(
        f".{_state_file_path.name}.{os.getpid()}.{get_ident()}.tmp"
    )
    temporary_path.write_text(
        json.dumps(_state_to_dict(state), ensure_ascii=False, sort_keys=True),
        encoding="utf-8",
    )
    temporary_path.chmod(0o600)
    temporary_path.replace(_state_file_path)


def _with_stale_recording_guard(state: RuntimeState) -> RuntimeState:
    if state.recording_status != "recording":
        return state
    if state.heartbeat_at is None:
        return replace(state, recording_status="unknown", last_error="stale_heartbeat")
    age_seconds = (_utcnow() - state.heartbeat_at).total_seconds()
    if age_seconds > RUNTIME_HEARTBEAT_TTL_SECONDS:
        return replace(state, recording_status="unknown", last_error="stale_heartbeat")
    return state


def get_runtime_state() -> RuntimeState:
    global _state
    with _lock:
        shared_state = _read_shared_state()
        if shared_state is not None:
            _state = shared_state
        return _with_stale_recording_guard(_state)


def set_recording_status(status: str, *, error: Optional[str] = None) -> RuntimeState:
    global _state
    now = _utcnow()

    with _lock:
        previous = _read_shared_state() or _state
        listener_started_at = previous.listener_started_at
        if status == "recording" and previous.recording_status != "recording":
            listener_started_at = now

        _state = RuntimeState(
            recording_status=status,
            status_updated_at=now,
            listener_started_at=listener_started_at,
            heartbeat_at=now,
            process_id=os.getpid(),
            last_error=error,
        )
        _write_shared_state(_state)
        return _state


def refresh_runtime_heartbeat() -> RuntimeState:
    """Refresh the shared heartbeat without changing the recording status."""
    global _state
    now = _utcnow()
    with _lock:
        current = _read_shared_state() or _state
        if current.recording_status != "recording":
            _state = current
            return current
        _state = replace(
            current,
            heartbeat_at=now,
            process_id=os.getpid(),
        )
        _write_shared_state(_state)
        return _state


def record_runtime_error(error: str) -> RuntimeState:
    """Expose a recoverable listener error without claiming recording stopped."""
    global _state
    now = _utcnow()
    with _lock:
        current = _read_shared_state() or _state
        _state = replace(
            current,
            status_updated_at=now,
            process_id=os.getpid(),
            last_error=error,
        )
        _write_shared_state(_state)
        return _state


def reset_runtime_state() -> RuntimeState:
    """Reset in-memory and shared state. Primarily used by tests."""
    global _state
    with _lock:
        _state = RuntimeState()
        try:
            _state_file_path.unlink()
        except FileNotFoundError:
            pass
        return _state
