import os
import re
from datetime import datetime, timezone

import requests
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI()

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class Message(BaseModel):
    text: str


WALLET_PATTERN = re.compile(r"^0x[a-fA-F0-9]{40}$")
ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DECIMALS_METHOD = "0x313ce567"
SYMBOL_METHOD = "0x95d89b41"
NAME_METHOD = "0x06fdde03"

SCAN_LOOKBACK_BLOCKS = 900
SCAN_WINDOW_SECONDS = 3 * 60 * 60
MARKET_LOG_PAGES = 2
MARKET_LOG_PAGE_SIZE = 1000
MIN_CLUSTER_WALLETS = 3
MIN_TOKEN_EVENTS = 4
MAX_METADATA_TOKENS = 25
LARGE_EVENT_PERCENTILE = 0.8
MAX_RESULTS = 5
STABLECOIN_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "USDS", "FDUSD", "PYUSD", "TUSD"}

UNSUPPORTED_SCAN_TERMS = {
    "sui": "SUI braucht eine eigene Sui-Datenquelle. Der aktuelle breite Scan deckt nur Ethereum ERC-20 Aktivitaet ab.",
    "plume": "PLUME braucht eine eigene Plume- oder EVM-Datenquelle. Der aktuelle breite Scan deckt nur Ethereum ERC-20 Aktivitaet ab.",
    "market": None,
}

TOKEN_METADATA_CACHE: dict[str, dict] = {}


def is_ethereum_wallet(text: str) -> bool:
    return bool(WALLET_PATTERN.fullmatch(text.strip()))


def get_etherscan_api_key() -> str | None:
    return os.getenv("ETHERSCAN_API_KEY")


def call_etherscan(params: dict) -> dict:
    response = requests.get(
        ETHERSCAN_BASE_URL,
        params=params,
        timeout=10,
    )
    response.raise_for_status()
    return response.json()


def fetch_eth_balance(wallet_address: str) -> str:
    api_key = get_etherscan_api_key()
    if not api_key:
        return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

    try:
        data = call_etherscan(
            {
                "chainid": "1",
                "module": "account",
                "action": "balance",
                "address": wallet_address,
                "tag": "latest",
                "apikey": api_key,
            }
        )
    except requests.RequestException:
        return "Fehler: Etherscan konnte gerade nicht erreicht werden."

    if data.get("status") != "1" or "result" not in data:
        message = data.get("message") or "Unbekannter API-Fehler."
        return f"Fehler: {message}"

    balance_wei = int(data["result"])
    balance_eth = balance_wei / 10**18
    return f"{balance_eth:.6f} ETH"


def fetch_recent_transactions(wallet_address: str) -> list[dict] | None:
    api_key = get_etherscan_api_key()
    if not api_key:
        return None

    try:
        data = call_etherscan(
            {
                "chainid": "1",
                "module": "account",
                "action": "txlist",
                "address": wallet_address,
                "startblock": "0",
                "endblock": "99999999",
                "page": "1",
                "offset": "3",
                "sort": "desc",
                "apikey": api_key,
            }
        )
    except requests.RequestException:
        return None

    result = data.get("result")
    if not isinstance(result, list):
        return None
    return result


def format_tx_direction(wallet_address: str, tx: dict) -> str:
    from_address = str(tx.get("from", "")).lower()
    to_address = str(tx.get("to", "")).lower()
    wallet_lower = wallet_address.lower()

    if to_address == wallet_lower:
        return "Eingang"
    if from_address == wallet_lower:
        return "Ausgang"
    return "Bewegung"


def format_wallet_summary(wallet_address: str) -> str:
    balance_text = fetch_eth_balance(wallet_address)
    if balance_text.startswith("Fehler:"):
        return balance_text

    recent_transactions = fetch_recent_transactions(wallet_address)
    if not recent_transactions:
        return (
            f"Wallet {wallet_address}\n"
            f"ETH Guthaben: {balance_text}\n"
            "Letzte Transaktionen: Keine Daten gefunden."
        )

    lines = [
        f"Wallet {wallet_address}",
        f"ETH Guthaben: {balance_text}",
        "Letzte Transaktionen:",
    ]

    for tx in recent_transactions:
        direction = format_tx_direction(wallet_address, tx)
        value_eth = int(tx.get("value", "0")) / 10**18
        tx_hash = str(tx.get("hash", ""))[:10]
        lines.append(f"- {direction}: {value_eth:.6f} ETH | Hash {tx_hash}...")

    return "\n".join(lines)


def fetch_latest_block_number() -> int | None:
    api_key = get_etherscan_api_key()
    if not api_key:
        return None

    data = call_etherscan(
        {
            "chainid": "1",
            "module": "proxy",
            "action": "eth_blockNumber",
            "apikey": api_key,
        }
    )

    result = data.get("result")
    if not isinstance(result, str):
        return None
    return int(result, 16)


def fetch_market_transfer_logs(from_block: int, to_block: int) -> list[dict]:
    api_key = get_etherscan_api_key()
    if not api_key:
        return []

    all_logs: list[dict] = []
    seen_keys: set[tuple[str, str]] = set()

    for page in range(1, MARKET_LOG_PAGES + 1):
        data = call_etherscan(
            {
                "chainid": "1",
                "module": "logs",
                "action": "getLogs",
                "fromBlock": str(from_block),
                "toBlock": str(to_block),
                "topic0": TRANSFER_TOPIC,
                "page": str(page),
                "offset": str(MARKET_LOG_PAGE_SIZE),
                "apikey": api_key,
            }
        )

        result = data.get("result")
        if not isinstance(result, list) or not result:
            break

        for log in result:
            log_key = (str(log.get("transactionHash", "")), str(log.get("logIndex", "")))
            if log_key not in seen_keys:
                seen_keys.add(log_key)
                all_logs.append(log)

        if len(result) < MARKET_LOG_PAGE_SIZE:
            break

    return all_logs


def parse_address_from_topic(topic: str) -> str:
    return f"0x{topic[-40:]}".lower()


def parse_focus_term(text: str) -> tuple[str | None, str | None]:
    parts = text.split(maxsplit=1)
    if len(parts) == 1:
        return None, None

    focus_term = parts[1].strip().lower()
    if not focus_term:
        return None, None

    limitation = UNSUPPORTED_SCAN_TERMS.get(focus_term)
    if limitation:
        return None, limitation
    if focus_term == "market":
        return None, None
    return focus_term, None


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


def call_contract_method(contract_address: str, method_signature: str) -> str | None:
    api_key = get_etherscan_api_key()
    if not api_key:
        return None

    data = call_etherscan(
        {
            "chainid": "1",
            "module": "proxy",
            "action": "eth_call",
            "to": contract_address,
            "data": method_signature,
            "tag": "latest",
            "apikey": api_key,
        }
    )
    return data.get("result")


def fetch_token_metadata_from_history(contract_address: str) -> dict | None:
    api_key = get_etherscan_api_key()
    if not api_key:
        return None

    data = call_etherscan(
        {
            "chainid": "1",
            "module": "account",
            "action": "tokentx",
            "contractaddress": contract_address,
            "page": "1",
            "offset": "1",
            "sort": "desc",
            "apikey": api_key,
        }
    )

    result = data.get("result")
    if not isinstance(result, list) or not result:
        return None

    first_item = result[0]
    decimals_text = str(first_item.get("tokenDecimal", ""))
    if not decimals_text.isdigit():
        return None

    return {
        "contract": contract_address,
        "decimals": int(decimals_text),
        "symbol": str(first_item.get("tokenSymbol", "")) or contract_address[:8],
        "name": str(first_item.get("tokenName", "")) or str(first_item.get("tokenSymbol", "")) or contract_address[:8],
    }


def resolve_token_metadata(contract_address: str) -> dict | None:
    contract_address = contract_address.lower()
    if contract_address in TOKEN_METADATA_CACHE:
        return TOKEN_METADATA_CACHE[contract_address]

    metadata = fetch_token_metadata_from_history(contract_address)
    if metadata is not None:
        TOKEN_METADATA_CACHE[contract_address] = metadata
        return metadata

    decimals_hex = call_contract_method(contract_address, DECIMALS_METHOD)
    symbol_hex = call_contract_method(contract_address, SYMBOL_METHOD)
    name_hex = call_contract_method(contract_address, NAME_METHOD)

    decimals = decode_uint256(decimals_hex or "")
    symbol = decode_abi_string(symbol_hex or "")
    name = decode_abi_string(name_hex or "")

    if decimals is None:
        return None

    metadata = {
        "contract": contract_address,
        "decimals": decimals,
        "symbol": symbol or contract_address[:8],
        "name": name or (symbol or contract_address[:8]),
    }
    TOKEN_METADATA_CACHE[contract_address] = metadata
    return metadata


def filter_erc20_logs(logs: list[dict]) -> list[dict]:
    filtered_logs = []
    for log in logs:
        topics = log.get("topics")
        data_hex = log.get("data")
        if not isinstance(topics, list) or len(topics) != 3:
            continue
        if not isinstance(data_hex, str) or data_hex == "0x":
            continue
        filtered_logs.append(log)
    return filtered_logs


def select_candidate_contracts(logs: list[dict]) -> list[str]:
    counts: dict[str, int] = {}
    for log in logs:
        contract = str(log.get("address", "")).lower()
        if contract:
            counts[contract] = counts.get(contract, 0) + 1

    ranked_contracts = sorted(counts.items(), key=lambda item: item[1], reverse=True)
    return [contract for contract, count in ranked_contracts if count >= MIN_TOKEN_EVENTS][:MAX_METADATA_TOKENS]


def parse_token_event(log: dict, metadata: dict) -> dict | None:
    topics = log.get("topics")
    data_hex = log.get("data")
    timestamp_hex = str(log.get("timeStamp", "0"))
    if not isinstance(topics, list) or len(topics) != 3 or not isinstance(data_hex, str):
        return None

    raw_amount = decode_uint256(data_hex)
    if raw_amount is None:
        return None

    try:
        timestamp = int(timestamp_hex, 16)
    except ValueError:
        return None

    amount = raw_amount / (10 ** metadata["decimals"])
    return {
        "contract": metadata["contract"],
        "symbol": metadata["symbol"],
        "name": metadata["name"],
        "from": parse_address_from_topic(str(topics[1])),
        "to": parse_address_from_topic(str(topics[2])),
        "amount": amount,
        "timestamp": timestamp,
    }


def calculate_large_event_threshold(amounts: list[float]) -> float | None:
    positive_amounts = sorted(amount for amount in amounts if amount > 0)
    if not positive_amounts:
        return None

    threshold_index = int((len(positive_amounts) - 1) * LARGE_EVENT_PERCENTILE)
    return positive_amounts[threshold_index]


def format_window(timestamp: int) -> str:
    window_start = timestamp - (timestamp % SCAN_WINDOW_SECONDS)
    window_end = window_start + SCAN_WINDOW_SECONDS
    start_text = datetime.fromtimestamp(window_start, tz=timezone.utc).strftime("%H:%M")
    end_text = datetime.fromtimestamp(window_end, tz=timezone.utc).strftime("%H:%M")
    return f"{start_text}-{end_text} UTC"


def classify_signal_strength(wallet_count: int) -> str:
    if wallet_count >= 10:
        return "starkes"
    if wallet_count >= 5:
        return "solides"
    return "fruehes"


def build_signal_reason(signal: dict) -> str:
    strength = classify_signal_strength(signal["wallet_count"])
    direction_text = "akkumulieren" if signal["direction"] == "accumulation" else "verteilen"
    return (
        f"{signal['wallet_count']} grosse Wallets {direction_text} {signal['symbol']} "
        f"im selben Zeitfenster. Das wirkt wie ein {strength} Cluster."
    )


def build_contract_signals(metadata: dict, logs: list[dict]) -> list[dict]:
    parsed_events = []
    for log in logs:
        event = parse_token_event(log, metadata)
        if event is not None:
            parsed_events.append(event)

    if len(parsed_events) < MIN_TOKEN_EVENTS:
        return []

    threshold = calculate_large_event_threshold([event["amount"] for event in parsed_events])
    if threshold is None or threshold <= 0:
        return []

    grouped_signals: dict[tuple[str, int], dict] = {}

    for event in parsed_events:
        if event["amount"] < threshold:
            continue

        bucket_start = event["timestamp"] - (event["timestamp"] % SCAN_WINDOW_SECONDS)
        directional_events = [
            ("accumulation", event["to"]),
            ("distribution", event["from"]),
        ]

        for direction, wallet in directional_events:
            signal_key = (direction, bucket_start)
            if signal_key not in grouped_signals:
                grouped_signals[signal_key] = {
                    "symbol": metadata["symbol"],
                    "name": metadata["name"],
                    "contract": metadata["contract"],
                    "direction": direction,
                    "wallets": set(),
                    "wallet_count": 0,
                    "time_window": format_window(event["timestamp"]),
                    "total_size": 0.0,
                    "event_count": 0,
                    "large_threshold": threshold,
                }

            grouped_signals[signal_key]["wallets"].add(wallet)
            grouped_signals[signal_key]["wallet_count"] = len(grouped_signals[signal_key]["wallets"])
            grouped_signals[signal_key]["total_size"] += event["amount"]
            grouped_signals[signal_key]["event_count"] += 1

    signals = []
    for signal in grouped_signals.values():
        if signal["wallet_count"] < MIN_CLUSTER_WALLETS:
            continue
        signal["wallets"] = list(signal["wallets"])
        signal["explanation"] = build_signal_reason(signal)
        signals.append(signal)

    return signals


def matches_focus(signal: dict, focus_term: str | None) -> bool:
    if not focus_term:
        return False

    haystacks = [
        signal["symbol"].lower(),
        signal["name"].lower(),
        signal["contract"].lower(),
    ]
    return any(focus_term in haystack for haystack in haystacks)


def rank_signals(signals: list[dict], focus_term: str | None) -> list[dict]:
    def sort_key(signal: dict) -> tuple:
        focus_bonus = 1 if matches_focus(signal, focus_term) else 0
        non_stable_bonus = 0 if signal["symbol"].upper() in STABLECOIN_SYMBOLS else 1
        return (
            focus_bonus,
            non_stable_bonus,
            signal["wallet_count"],
            signal["event_count"],
            signal["total_size"],
        )

    return sorted(signals, key=sort_key, reverse=True)


def format_scan_response(signals: list[dict], focus_term: str | None, sampled_logs: int) -> str:
    lines = [
        "Scan fertig. Starke Whale-Signale aus der aktuellen Ethereum-Transfer-Stichprobe:",
    ]

    for index, signal in enumerate(signals[:MAX_RESULTS], start=1):
        lines.append(
            f"{index}. {signal['symbol']} | {signal['direction']} | "
            f"{signal['wallet_count']} grosse Wallets | {signal['time_window']} | "
            f"{signal['total_size']:.2f} {signal['symbol']} | {signal['explanation']}"
        )

    if focus_term:
        if any(matches_focus(signal, focus_term) for signal in signals):
            lines.append(f"Priorisiert auf: {focus_term.upper()}")
        else:
            lines.append(f"Kein direktes Signal fuer {focus_term.upper()} im aktuellen Sample gefunden.")
    else:
        lines.append("Signal-first Modus: Tokens werden erst aus den Events entdeckt, nicht vorgegeben.")

    lines.append(
        f"Real: ERC-20 Transfer-Logs aus {sampled_logs} Events auf Ethereum. "
        "Limit: Etherscan liefert hier nur eine Stichprobe, nicht den kompletten Markt."
    )
    lines.append(
        "Proxy-Logik: accumulation/distribution wird aus grossen Token-Transfers abgeleitet, "
        "nicht aus bestaetigten DEX-Buys oder DEX-Sells."
    )
    return "\n".join(lines)


def scan_whale_token_activity(text: str) -> str:
    api_key = get_etherscan_api_key()
    if not api_key:
        return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

    focus_term, limitation = parse_focus_term(text)
    if limitation:
        return limitation

    try:
        latest_block = fetch_latest_block_number()
        if latest_block is None:
            return "Fehler: Letzter Ethereum-Block konnte nicht gelesen werden."

        from_block = max(latest_block - SCAN_LOOKBACK_BLOCKS, 0)
        market_logs = fetch_market_transfer_logs(from_block, latest_block)
        erc20_logs = filter_erc20_logs(market_logs)
        if not erc20_logs:
            return "Fehler: Keine brauchbaren ERC-20 Transfer-Logs fuer den breiten Scan gefunden."

        candidate_contracts = select_candidate_contracts(erc20_logs)
        if not candidate_contracts:
            return "Keine auffaelligen Token-Cluster im aktuellen Markt-Sample gefunden."

        logs_by_contract: dict[str, list[dict]] = {}
        for log in erc20_logs:
            contract = str(log.get("address", "")).lower()
            if contract in candidate_contracts:
                logs_by_contract.setdefault(contract, []).append(log)

        signals = []
        for contract in candidate_contracts:
            metadata = resolve_token_metadata(contract)
            if metadata is None:
                continue
            contract_signals = build_contract_signals(metadata, logs_by_contract.get(contract, []))
            signals.extend(contract_signals)

        if not signals:
            return (
                "Kein starkes Whale-Cluster gefunden. "
                "Der Scan ist echt breit ueber ERC-20 Transfers, aber das aktuelle Sample zeigt nichts Starkes."
            )

        ranked_signals = rank_signals(signals, focus_term)
        return format_scan_response(ranked_signals, focus_term, len(erc20_logs))
    except requests.RequestException:
        return "Fehler: Der breite Token-Scan ueber Etherscan ist fehlgeschlagen."
    except ValueError:
        return "Fehler: Etherscan hat ungueltige Daten fuer den breiten Token-Scan geliefert."


@app.get("/")
def read_root():
    return {"message": "Bot laeuft"}


@app.post("/message")
def handle_message(msg: Message):
    original_text = msg.text.strip()
    text = original_text.lower()

    if is_ethereum_wallet(original_text):
        return {"response": format_wallet_summary(original_text)}
    if text.startswith("scan"):
        return {"response": scan_whale_token_activity(text)}

    if "hallo" in text:
        return {"response": "Hey"}
    if "hilfe" in text:
        return {
            "response": (
                "Schick mir eine Ethereum Wallet-Adresse fuer den Direktcheck. "
                "Mit scan suche ich breit nach Whale-Clustern in Ethereum ERC-20 Transfers."
            )
        }
    if "preis" in text:
        return {"response": "Kommt drauf an"}
    return {"response": "Noch nicht gelernt"}
