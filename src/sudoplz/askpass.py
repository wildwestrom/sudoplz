"""Askpass helper invoked by ``sudo -A``.

Pops a GUI password prompt showing the exact command about to run, then
prints whatever the user typed to stdout. Sudo itself validates the
password against the system — this script never stores or checks it.
Never write anything else to stdout — sudo treats stray output as the
password.
"""

from __future__ import annotations

import getpass
import json
import os
import socket
import subprocess
import sys
import syslog
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

from sudoplz.core import (
    AUDIT_LOG_FILE,
    RATE_LIMIT_FILE,
    load_config,
    parent_command,
    process_name,
)


def repair_environment() -> None:
    """Restore env vars that ``sudo -A`` strips but our subprocesses need."""
    if sys.platform == "darwin":
        brew = "/opt/homebrew/bin"
        if os.path.isdir(brew) and brew not in os.environ.get("PATH", ""):
            os.environ["PATH"] = f"{brew}:{os.environ.get('PATH', '')}"


def prompt_password_gui(user: str, host: str, command: str) -> str | None:
    """Show a GUI password prompt. Return the typed password, or None on cancel/error."""
    message = f"User: {user}\nHost: {host}\nCommand: {command}\n\nSudo password:"

    if sys.platform == "darwin":
        escaped = message.replace("\\", "\\\\").replace('"', '\\"').replace("\n", "\\n")
        script = (
            'tell application "System Events"\nactivate\n'
            f'display dialog "{escaped}" '
            'default answer "" with hidden answer '
            'with title "Sudo Authentication Required" '
            "with icon caution giving up after 30\nend tell"
        )
        try:
            result = subprocess.run(
                ["osascript", "-e", script], capture_output=True, text=True, timeout=35
            )
            if result.returncode != 0:
                return None
            for part in result.stdout.split(", "):
                if part.startswith("text returned:"):
                    return part.removeprefix("text returned:").rstrip("\n")
            return None
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            syslog.syslog(syslog.LOG_WARNING, f"osascript password dialog failed: {e}")
            return None

    if "DISPLAY" not in os.environ:
        return None

    try:
        result = subprocess.run(
            [
                "zenity",
                "--password",
                "--title=Sudo Authentication Required",
                f"--text={message}",
            ],
            capture_output=True,
            text=True,
            timeout=60,
        )
        return result.stdout.rstrip("\n") if result.returncode == 0 else None
    except FileNotFoundError:
        syslog.syslog(
            syslog.LOG_ERR,
            "zenity not found; install it (apt install zenity)",
        )
        return None
    except subprocess.TimeoutExpired:
        syslog.syslog(syslog.LOG_WARNING, "zenity password dialog timed out")
        return None


def prompt_password_tty(user: str, host: str, command: str) -> str | None:
    """Headless fallback: prompt for the sudo password on /dev/tty."""
    try:
        with open("/dev/tty", "w") as tty_out:
            tty_out.write(
                f"\n{'=' * 50}\nSUDO AUTHENTICATION REQUIRED\n{'=' * 50}\n"
                f"User: {user}\nHost: {host}\nCommand: {command}\n{'-' * 50}\n"
            )
            tty_out.flush()
            return getpass.getpass("Sudo password: ", stream=tty_out) or None
    except OSError:
        return None


def check_rate_limit(max_attempts: int, lockout_minutes: int) -> bool:
    """Enforce per-hour attempt ceiling with lockout.

    Fails closed on corruption — a broken rate-limit file means we can't
    count attempts, which means we can't safely bypass the guard.
    """
    RATE_LIMIT_FILE.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = (
            json.loads(RATE_LIMIT_FILE.read_text())
            if RATE_LIMIT_FILE.exists()
            else {"attempts": [], "lockout_until": None}
        )
    except (OSError, json.JSONDecodeError) as e:
        syslog.syslog(syslog.LOG_ERR, f"Rate limit file unreadable, failing closed: {e}")
        sys.stderr.write(
            f"Error: rate limit file at {RATE_LIMIT_FILE} is unreadable. Delete it to reset.\n"
        )
        return False

    now = datetime.now()
    if data.get("lockout_until"):
        lockout = datetime.fromisoformat(data["lockout_until"])
        if now < lockout:
            remaining = int((lockout - now).total_seconds() / 60)
            syslog.syslog(syslog.LOG_WARNING, f"Rate limit lockout: {remaining} min remaining")
            return False
        data["lockout_until"] = None

    one_hour_ago = now - timedelta(hours=1)
    data["attempts"] = [a for a in data["attempts"] if datetime.fromisoformat(a) > one_hour_ago]

    if len(data["attempts"]) >= max_attempts:
        data["lockout_until"] = (now + timedelta(minutes=lockout_minutes)).isoformat()
        syslog.syslog(syslog.LOG_WARNING, f"Rate limit exceeded; lockout for {lockout_minutes} min")
        RATE_LIMIT_FILE.write_text(json.dumps(data))
        return False

    data["attempts"].append(now.isoformat())
    RATE_LIMIT_FILE.write_text(json.dumps(data))
    return True


def _path_is_allowed(cwd: str, allowed: list[str]) -> bool:
    for raw in allowed:
        p = os.path.normpath(raw)
        if cwd == p or cwd.startswith(p + os.sep):
            return True
    return False


def check_security(config: dict[str, Any]) -> bool:
    if not check_rate_limit(config["max_attempts_per_hour"], config["lockout_minutes"]):
        return False

    cwd = os.path.normpath(os.getcwd())
    if not _path_is_allowed(cwd, config["allowed_paths"]):
        syslog.syslog(syslog.LOG_WARNING, f"Askpass called from unauthorized path: {cwd}")
        return False

    proc = process_name(os.getppid())
    if proc not in config["allowed_processes"]:
        syslog.syslog(syslog.LOG_WARNING, f"Askpass called by unauthorized process: {proc}")
        return False

    if not (os.getenv("SSH_AUTH_SOCK") or os.getenv("SSH_TTY") or os.getenv("TERM")):
        syslog.syslog(syslog.LOG_WARNING, "Askpass called without terminal/SSH env")
        return False

    return True


def validate_script_integrity() -> bool:
    """Refuse to run if our own module file is world-writable.

    Group-write is tolerated because user-local installs under
    common umasks produce 664 files where the group is a single-member
    user group. World-write is the real threat — anyone on the box
    could rewrite the script to leak passwords.
    """
    this_file = Path(__file__).resolve()
    os.environ["SUDO_ASKPASS"] = str(this_file)
    stats = this_file.stat()
    if stats.st_mode & 0o002:
        syslog.syslog(
            syslog.LOG_CRIT, f"Askpass module is world-writable: {oct(stats.st_mode)}"
        )
        return False
    return True


def write_audit_entry(ppid: int, proc: str | None, command: str) -> None:
    try:
        AUDIT_LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "timestamp": datetime.now().isoformat(),
            "pid": ppid,
            "process": proc or "unknown",
            "command": command,
            "user": os.environ.get("USER", "unknown"),
            "cwd": os.getcwd(),
            "status": "prompted",
        }
        with AUDIT_LOG_FILE.open("a") as f:
            f.write(json.dumps(entry) + "\n")
    except OSError as e:
        syslog.syslog(syslog.LOG_WARNING, f"Could not write audit log: {e}")


def main() -> None:
    syslog.openlog("sudoplz")
    repair_environment()

    if not validate_script_integrity():
        print("Error: environment validation failed", file=sys.stderr)
        sys.exit(1)

    config = load_config()

    if not check_security(config):
        print("Error: security check failed", file=sys.stderr)
        syslog.syslog(syslog.LOG_ERR, "Security check failed")
        sys.exit(1)

    ppid = os.getppid()
    command = parent_command(ppid)
    write_audit_entry(ppid, process_name(ppid), command)

    user = os.environ.get("USER", "unknown")
    host = socket.gethostname()

    if "DISPLAY" in os.environ or sys.platform == "darwin":
        password = prompt_password_gui(user, host, command)
    else:
        password = prompt_password_tty(user, host, command)

    if not password:
        syslog.syslog(syslog.LOG_WARNING, "Sudo password prompt cancelled or empty")
        print("Error: no password entered", file=sys.stderr)
        sys.exit(1)

    print(password)


if __name__ == "__main__":
    main()
