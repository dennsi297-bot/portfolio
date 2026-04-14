def decode_uint256(hex_value: str) -> int | None:
    if not isinstance(hex_value, str) or not hex_value.startswith("0x"):
        return None
    try:
        return int(hex_value, 16)
    except ValueError:
        return None


def decode_abi_string(hex_value: str) -> str | None:
    if not isinstance(hex_value, str) or not hex_value.startswith("0x"):
        return None

    body = hex_value[2:]
    if not body:
        return None

    if len(body) == 64:
        text = bytes.fromhex(body).rstrip(b"\x00").decode("utf-8", errors="ignore").strip()
        return text or None

    if len(body) < 128:
        return None

    try:
        length = int(body[64:128], 16)
    except ValueError:
        return None

    start = 128
    end = start + (length * 2)
    if end > len(body):
        return None

    text = bytes.fromhex(body[start:end]).decode("utf-8", errors="ignore").strip("\x00").strip()
    return text or None
