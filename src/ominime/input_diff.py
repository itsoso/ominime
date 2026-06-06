"""Helpers for detecting text committed by IME/voice input."""


def extract_inserted_text(before: str | None, after: str | None) -> str:
    """Return text inserted between two snapshots.

    This handles append, middle insertion, and selected-text replacement by
    trimming the common prefix and suffix. Pure deletions are ignored.
    """
    before = before or ""
    after = after or ""

    if not after or before == after:
        return ""

    prefix_len = 0
    max_prefix = min(len(before), len(after))
    while prefix_len < max_prefix and before[prefix_len] == after[prefix_len]:
        prefix_len += 1

    before_suffix = len(before)
    after_suffix = len(after)
    while (
        before_suffix > prefix_len
        and after_suffix > prefix_len
        and before[before_suffix - 1] == after[after_suffix - 1]
    ):
        before_suffix -= 1
        after_suffix -= 1

    return after[prefix_len:after_suffix]
