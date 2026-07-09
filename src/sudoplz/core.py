"""Shared helpers for askpass and sudoplz."""

from __future__ import annotations

import json
import os
import subprocess
import syslog
from pathlib import Path
from typing import Any

HOME = Path.home()
CONFIG_DIR = HOME / ".config" / "sudoplz"
CONFIG_FILE = CONFIG_DIR / "config.json"
RATE_LIMIT_FILE = CONFIG_DIR / "rate_limit.json"
AUDIT_LOG_FILE = CONFIG_DIR / "audit.log"

DEFAULT_CONFIG: dict[str, Any] = {
    "allowed_paths": [str(HOME), "/tmp/"],
    "allowed_processes": ["sudo", "claude-code", "code", "bash", "sh", "zsh", "fish"],
    "max_attempts_per_hour": 30,
    "lockout_minutes": 15,
}


def load_config() -> dict[str, Any]:
    """Merge DEFAULT_CONFIG with ~/.config/sudoplz/config.json."""
    config = dict(DEFAULT_CONFIG)
    if not CONFIG_FILE.exists():
        return config
    try:
        with CONFIG_FILE.open() as f:
            config.update(json.load(f))
    except (OSError, json.JSONDecodeError) as e:
        syslog.syslog(syslog.LOG_WARNING, f"Ignoring malformed config {CONFIG_FILE}: {e}")
    return config


def process_name(pid: int) -> str | None:
    """Resolve a PID's command name via `ps`, or None on failure."""
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "comm="])
        return os.path.basename(out.decode().strip())
    except subprocess.CalledProcessError:
        return None


def parent_command(pid: int) -> str:
    """Return the parent process's full command line, or 'Unknown command'."""
    try:
        out = subprocess.check_output(["ps", "-p", str(pid), "-o", "args="])
        parts = out.decode().strip().split()
        if parts and "sudo" in parts[0]:
            for i, part in enumerate(parts):
                if part != "sudo" and not part.startswith("-"):
                    return " ".join(parts[i:])
        return " ".join(parts) or "Unknown command"
    except subprocess.CalledProcessError:
        return "Unknown command"
