"""Submission-time input snapshot helpers."""

SubmissionSnapshot = tuple[str, str, str]
PreviousSubmissionSnapshot = tuple[str, str, str, float] | None


def normalize_submission_text(text: str | None) -> str:
    """Return the full input value to save, or empty string when ignorable."""
    if text is None:
        return ""
    return text if text.strip() else ""


def should_save_submission_snapshot(
    current: SubmissionSnapshot,
    previous: PreviousSubmissionSnapshot,
    now: float,
    debounce_seconds: float,
) -> bool:
    """Avoid saving duplicate Enter repeats for the same app/content."""
    if previous is None:
        return True

    app_name, bundle_id, content = current
    prev_app_name, prev_bundle_id, prev_content, prev_time = previous
    return not (
        app_name == prev_app_name
        and bundle_id == prev_bundle_id
        and content == prev_content
        and now - prev_time < debounce_seconds
    )
