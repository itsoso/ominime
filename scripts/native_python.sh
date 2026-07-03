#!/bin/bash
# Shared Python runtime checks for OmniMe install scripts.

ominime_python_arch() {
    local python_path="$1"
    "$python_path" -c 'import platform; print(platform.machine())'
}

ominime_python_version() {
    local python_path="$1"
    "$python_path" -c 'import sys; print(".".join(map(str, sys.version_info[:3])))'
}

ominime_require_python_version() {
    local python_path="$1"
    local minimum_version="${2:-3.10}"

    "$python_path" - "$minimum_version" <<'PY'
import sys

minimum = tuple(int(part) for part in sys.argv[1].split("."))
current = sys.version_info[: len(minimum)]

if current < minimum:
    print(
        f"OmniMe requires Python {sys.argv[1]} or newer; "
        f"detected {sys.version.split()[0]} at {sys.executable}",
        file=sys.stderr,
    )
    sys.exit(1)
PY
}

ominime_require_native_python() {
    local python_path="$1"
    local host_arch
    local python_arch

    if [ ! -x "$python_path" ]; then
        echo "Python is not executable: $python_path" >&2
        return 1
    fi

    host_arch="$(uname -m)"
    python_arch="$(ominime_python_arch "$python_path")"

    if [ "$host_arch" = "arm64" ] && [ "${OMINIME_ALLOW_X86_64_PYTHON:-}" != "1" ]; then
        case "$python_arch" in
            arm64|arm64e)
                ;;
            *)
                echo "OmniMe is running on Apple silicon, but this Python is $python_arch: $python_path" >&2
                echo "Use a native Python such as /opt/homebrew/bin/python3, or set OMINIME_ALLOW_X86_64_PYTHON=1 to override." >&2
                return 1
                ;;
        esac
    fi
}

ominime_select_python() {
    local minimum_version="${1:-3.10}"
    local host_arch
    local candidates=()
    local candidate

    host_arch="$(uname -m)"

    if [ -n "${PYTHON_BIN:-}" ]; then
        candidates+=("$PYTHON_BIN")
    elif [ "$host_arch" = "arm64" ]; then
        candidates+=("/opt/homebrew/bin/python3")
        candidates+=("$(command -v python3 2>/dev/null || true)")
        candidates+=("/usr/bin/python3")
        candidates+=("/usr/local/bin/python3")
    else
        candidates+=("$(command -v python3 2>/dev/null || true)")
        candidates+=("/usr/local/bin/python3")
        candidates+=("/usr/bin/python3")
    fi

    for candidate in "${candidates[@]}"; do
        if [ -z "$candidate" ] || [ ! -x "$candidate" ]; then
            continue
        fi

        if ominime_require_python_version "$candidate" "$minimum_version" >/dev/null 2>&1 &&
            ominime_require_native_python "$candidate" >/dev/null 2>&1; then
            printf '%s\n' "$candidate"
            return 0
        fi
    done

    echo "Unable to find a native Python ${minimum_version}+ for OmniMe." >&2
    if [ "$host_arch" = "arm64" ]; then
        echo "Install arm64 Homebrew Python, then rerun with PYTHON_BIN=/opt/homebrew/bin/python3." >&2
    fi
    return 1
}
