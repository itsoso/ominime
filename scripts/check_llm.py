#!/usr/bin/env python3
"""Explicit network/model smoke check for the configured LLM backend."""

import os
from pathlib import Path
import sys


project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root / "src"))

from dotenv import load_dotenv

load_dotenv(project_root / ".env")

from ominime.llm_backend import LLMMessage, get_llm_backend


def check_backend() -> bool:
    backend_type = os.getenv("LLM_BACKEND", "ollama")
    print(f"LLM_BACKEND: {backend_type}")

    try:
        backend = get_llm_backend()
        if backend is None or not backend.is_available():
            print("LLM backend unavailable")
            return False
        response = backend.chat(
            messages=[LLMMessage(role="user", content="Reply with: ok")],
            temperature=0,
            max_tokens=10,
        )
    except Exception as exc:
        print(f"LLM check failed: {exc}")
        return False

    print(f"LLM backend ready: {response.model}")
    return True


if __name__ == "__main__":
    raise SystemExit(0 if check_backend() else 1)
