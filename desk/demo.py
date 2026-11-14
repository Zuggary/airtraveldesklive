"""Replay-shot switch: AN11_DEMO=1 makes the AN11 layers read the clearly SYNTHETIC fixtures (never in live runs)."""
import os


def on() -> bool:
    return os.environ.get("AN11_DEMO", "").strip().lower() not in ("", "0", "false", "no")
