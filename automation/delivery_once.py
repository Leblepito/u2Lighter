#!/usr/bin/env python3
"""Run a single delivery check (used by .github/workflows/delivery.yml).

delivery_notify.py's main() loops forever; in CI we only need one pass of check_and_notify().
"""
import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import delivery_notify  # noqa: E402


def main() -> int:
    print(f"[DELIVERY] Repo: {delivery_notify.GITHUB_REPO}")
    print(f"[DELIVERY] Email: {'enabled' if delivery_notify.EmailSender().enabled else 'disabled (demo mode)'}")
    notified = asyncio.run(delivery_notify.check_and_notify())
    print(f"[DELIVERY] Notifications sent: {notified}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
