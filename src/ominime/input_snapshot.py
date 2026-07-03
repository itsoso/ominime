"""Submission-time input snapshot helpers."""

SubmissionSnapshot = tuple[str, str, str]
PreviousSubmissionSnapshot = tuple[str, str, str, float] | None

TERMINAL_MAX_SUBMISSION_CHARS = 512

_TERMINAL_BUNDLE_IDS = {
    "co.zeit.hyper",
    "com.apple.console",
    "com.apple.terminal",
    "com.github.wez.wezterm",
    "com.googlecode.iterm2",
    "com.mitchellh.ghostty",
    "com.warp.warp-stable",
    "dev.warp.warp-stable",
    "io.alacritty",
    "net.kovidgoyal.kitty",
    "org.alacritty",
}

_TERMINAL_APP_NAME_HINTS = (
    "alacritty",
    "console",
    "ghostty",
    "hyper",
    "iterm",
    "kitty",
    "terminal",
    "wezterm",
    "warp",
    "控制台",
    "终端",
)

_BROWSER_BUNDLE_IDS = {
    "com.apple.safari",
    "com.brave.browser",
    "com.google.chrome",
    "com.microsoft.edgemac",
    "org.mozilla.firefox",
}

_BROWSER_APP_NAME_HINTS = (
    "brave",
    "chrome",
    "edge",
    "firefox",
    "safari",
)

_BROWSER_LOCATION_SUGGESTION_MARKERS = (
    "location from history",
    "location from bookmarks",
    "search suggestion",
    "依次按 tab",
)


def normalize_submission_text(
    text: str | None,
    app_name: str | None = None,
    bundle_id: str | None = None,
) -> str:
    """Return the full input value to save, or empty string when ignorable."""
    if text is None:
        return ""
    if not text.strip():
        return ""
    if _is_terminal_like_app(app_name, bundle_id):
        return _normalize_terminal_submission_text(text)
    if _is_browser_location_suggestion(text, app_name, bundle_id):
        return ""
    return text


def format_submission_terminal_notice(text: str) -> str:
    """Return a concise terminal notice without echoing submitted content."""
    return f"saved {len(text)} chars"


def _is_terminal_like_app(app_name: str | None, bundle_id: str | None) -> bool:
    normalized_bundle_id = (bundle_id or "").casefold()
    if normalized_bundle_id in _TERMINAL_BUNDLE_IDS:
        return True

    normalized_app_name = (app_name or "").casefold()
    return any(hint in normalized_app_name for hint in _TERMINAL_APP_NAME_HINTS)


def _is_browser_like_app(app_name: str | None, bundle_id: str | None) -> bool:
    normalized_bundle_id = (bundle_id or "").casefold()
    if normalized_bundle_id in _BROWSER_BUNDLE_IDS:
        return True

    normalized_app_name = (app_name or "").casefold()
    return any(hint in normalized_app_name for hint in _BROWSER_APP_NAME_HINTS)


def _is_browser_location_suggestion(
    text: str,
    app_name: str | None,
    bundle_id: str | None,
) -> bool:
    if not _is_browser_like_app(app_name, bundle_id):
        return False

    normalized_text = text.casefold()
    return any(marker in normalized_text for marker in _BROWSER_LOCATION_SUGGESTION_MARKERS)


def _normalize_terminal_submission_text(text: str) -> str:
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    for raw_line in reversed(lines):
        candidate = raw_line.strip()
        if not candidate:
            continue
        if len(candidate) > TERMINAL_MAX_SUBMISSION_CHARS:
            return ""
        return candidate
    return ""


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
