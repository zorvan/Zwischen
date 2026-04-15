#!/usr/bin/env python3
"""
End-to-End Test Report - Coordination Engine Telegram Bot
Date: 2026-04-16
"""

import subprocess
import sys


def run_tests():
    """Run pytest and capture output."""
    result = subprocess.run(
        [sys.executable, "-m", "pytest", "tests/", "-v"],
        cwd="/home/zorvan/Work/projects/Zwischen/telegram-bot",
        capture_output=True,
        text=True,
        timeout=300,
    )
    return result


def main():
    print("Running end-to-end tests for the telegram bot...")
    print("=" * 60)

    result = run_tests()

    print(result.stdout)
    if result.stderr:
        print("STDERR:", result.stderr)

    print("=" * 60)
    print("\nTest Summary:")
    print(f"Return code: {result.returncode}")

    if result.returncode == 0:
        print("✓ All tests passed!")
    else:
        print("✗ Some tests failed")
        print(f"  (exit code: {result.returncode})")


if __name__ == "__main__":
    main()
