import re
from datetime import datetime, timezone


WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")


def is_ethereum_wallet(text: str) -> bool:
    return bool(WALLET_PATTERN.fullmatch(text.strip()))


def parse_address_from_topic(topic: str) -> str:
    return f"0x{topic[-40:]}".lower()


def format_time_window(timestamp: int, window_seconds: int) -> str:
    window_start = timestamp - (timestamp % window_seconds)
    window_end = window_start + window_seconds
    start_text = datetime.fromtimestamp(window_start, tz=timezone.utc).strftime("%H:%M")
    end_text = datetime.fromtimestamp(window_end, tz=timezone.utc).strftime("%H:%M")
    return f"{start_text}-{end_text} UTC"
