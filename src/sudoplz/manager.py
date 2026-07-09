"""sudoplz — CLI to test and inspect the askpass integration."""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime

from sudoplz.core import AUDIT_LOG_FILE, CONFIG_DIR, CONFIG_FILE, load_config


def cmd_test(_args: argparse.Namespace) -> bool:
    askpass = shutil.which("askpass")
    if not askpass:
        print(
            "Error: 'askpass' not on PATH. Install with 'uv tool install .' first.",
            file=sys.stderr,
        )
        return False

    env = os.environ.copy()
    env["SUDO_ASKPASS"] = askpass
    print(f"Testing sudo -A with {askpass}...")
    result = subprocess.run(
        ["sudo", "-A", "echo", "Success!"], env=env, capture_output=True, text=True
    )
    if result.returncode == 0:
        print(f"Test successful: {result.stdout.strip()}")
        return True
    print(f"Test failed: {result.stderr.strip()}", file=sys.stderr)
    return False


def cmd_config(args: argparse.Namespace) -> bool:
    config = load_config()

    if args.show:
        print(json.dumps(config, indent=2))
        return True

    if args.max_attempts_per_hour is not None:
        if args.max_attempts_per_hour < 1:
            print("Error: --max-attempts-per-hour must be positive", file=sys.stderr)
            return False
        config["max_attempts_per_hour"] = args.max_attempts_per_hour
    elif args.lockout_minutes is not None:
        if args.lockout_minutes < 0:
            print("Error: --lockout-minutes must be 0 or positive", file=sys.stderr)
            return False
        config["lockout_minutes"] = args.lockout_minutes
    else:
        print(
            "Error: specify --show, --max-attempts-per-hour N, or --lockout-minutes N",
            file=sys.stderr,
        )
        return False

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    CONFIG_FILE.write_text(json.dumps(config, indent=2) + "\n")
    CONFIG_FILE.chmod(0o600)
    print("Configuration updated.")
    return True


def cmd_audit(_args: argparse.Namespace) -> bool:
    if not AUDIT_LOG_FILE.exists():
        print("No audit log found")
        return True
    lines = AUDIT_LOG_FILE.read_text().splitlines()[-50:]
    print(f"\nRecent askpass usage (last {len(lines)} entries):")
    print("-" * 80)
    for line in lines:
        try:
            entry = json.loads(line)
            ts = datetime.fromisoformat(entry["timestamp"]).strftime("%Y-%m-%d %H:%M:%S")
            cmd = entry.get("command", "")
            print(
                f"{ts} | user={entry.get('user', '?')} | "
                f"proc={entry.get('process', '?')} | cmd={cmd[:60]}"
            )
        except (json.JSONDecodeError, KeyError):
            continue
    print("-" * 80)
    return True


def main() -> None:
    parser = argparse.ArgumentParser(
        prog="sudoplz",
        description="Test and inspect the sudoplz askpass integration.",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)
    commands = [
        ("test", "Test sudo -A integration", cmd_test),
        ("audit", "Show recent askpass usage", cmd_audit),
    ]
    for name, help_text, fn in commands:
        p = sub.add_parser(name, help=help_text)
        p.set_defaults(func=fn)

    config_parser = sub.add_parser("config", help="View or modify sudoplz configuration")
    config_group = config_parser.add_mutually_exclusive_group(required=True)
    config_group.add_argument("--show", action="store_true", help="Print current configuration")
    config_group.add_argument(
        "--max-attempts-per-hour",
        type=int,
        metavar="N",
        help="Set max askpass invocations per hour before lockout",
    )
    config_group.add_argument(
        "--lockout-minutes",
        type=int,
        metavar="N",
        help="Set lockout duration in minutes after exceeding the rate limit",
    )
    config_parser.set_defaults(func=cmd_config)

    args = parser.parse_args()
    sys.exit(0 if args.func(args) else 1)


if __name__ == "__main__":
    main()
