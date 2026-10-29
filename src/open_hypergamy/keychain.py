"""Secret lookup: environment first, then the macOS Keychain (LLD §2, §17).

launchd jobs do not inherit your shell environment, so tokens live in the Keychain
(service `OpenHypergamy`). Secrets are never written to YAML, SQLite, logs or plists.
Set `OHG_USE_KEYCHAIN=0` to disable the Keychain (tests, non-macOS).
"""

from __future__ import annotations

import functools
import os
import subprocess
import sys
from collections.abc import Callable

SERVICE = "OpenHypergamy"
KNOWN = ("TELEGRAM_BOT_TOKEN", "TELEGRAM_CHAT_ID", "OHG_FREELLMAPI_API_KEY")

Runner = Callable[[list[str], str | None], tuple[int, str]]


def _run(args: list[str], stdin: str | None = None) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["/usr/bin/security", *args],
            input=stdin,
            capture_output=True,
            text=True,
            timeout=10,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return 1, ""
    return p.returncode, p.stdout.strip()


_runner: Runner = _run  # replaced in tests


def keychain_enabled() -> bool:
    return sys.platform == "darwin" and os.environ.get("OHG_USE_KEYCHAIN", "1") != "0"


@functools.lru_cache(maxsize=32)
def _from_keychain(name: str) -> str:
    rc, out = _runner(["find-generic-password", "-s", SERVICE, "-a", name, "-w"], None)
    return out if rc == 0 else ""


def clear_cache() -> None:
    _from_keychain.cache_clear()


def get_secret(name: str) -> str:
    """Value from the environment, else the Keychain, else ''. Never raises."""
    value = os.environ.get(name, "")
    if value or not keychain_enabled():
        return value
    return _from_keychain(name)


def source_of(name: str) -> str:
    if os.environ.get(name):
        return "environment"
    return "keychain" if keychain_enabled() and _from_keychain(name) else "unset"


def set_secret(name: str, value: str) -> None:
    # Limitation of /usr/bin/security: the value is passed as an argument, so it is briefly
    # visible to the same user in the process list while this command runs.
    rc, _ = _runner(["add-generic-password", "-U", "-s", SERVICE, "-a", name, "-w", value], None)
    if rc != 0:
        raise RuntimeError("could not write to the macOS Keychain")
    clear_cache()


def delete_secret(name: str) -> bool:
    rc, _ = _runner(["delete-generic-password", "-s", SERVICE, "-a", name], None)
    clear_cache()
    return rc == 0
