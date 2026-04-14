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
SCAN_LOOKBACK_BLOCKS = 900
SCAN_WINDOW_SECONDS = 3 * 60 * 60
MIN_CLUSTER_WALLETS = 3
MAX_RESULTS = 5

TRACKED_TOKENS = {
    "ondo": {
        "symbol": "ONDO",
        "contract": "0xfaba6f8e4a5e8ab82f62fe7c39859fa577269be3",
        "decimals": 18,
        "large_threshold": 100000.0,
        "aliases": ["ondo"],
    },
    "eth": {
        "symbol": "ETH",
        "contract": "0xc02aaa39b223fe8d0a0e5c4f27ead9083c756cc2",
        "decimals": 18,
        "large_threshold": 150.0,
        "aliases": ["eth", "weth"],
    },
    "btc": {
        "symbol": "BTC",
        "contract": "0x2260fac5e5542a773aa44fbcfedf7c193bc2c599",
        "decimals": 8,
        "large_threshold": 10.0,
        "aliases": ["btc", "wbtc"],
    },
    "polygon": {
        "symbol": "POL",
        "contract": "0x455e53cbb86018ac2b8092fdcd39d8444affc3f6",
        "decimals": 18,
        "large_threshold": 500000.0,
        "aliases": ["polygon", "matic", "pol"],
    },
}

UNSUPPORTED_TOKENS = {
    "sui": "SUI braucht eine eigene Sui-Datenquelle und ist in diesem Ethereum-Scanner noch Platzhalter.",
    "plume": "PLUME braucht eine eigene Chain- oder Explorer-Anbindung und ist hier noch Platzhalter.",
}


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


def fetch_token_transfer_logs(contract_address: str, from_block: int, to_block: int) -> list[dict]:
    api_key = get_etherscan_api_key()
    if not api_key:
        return []

    data = call_etherscan(
        {
            "chainid": "1",
            "module": "logs",
            "action": "getLogs",
            "fromBlock": str(from_block),
            "toBlock": str(to_block),
            "address": contract_address,
            "topic0": TRANSFER_TOPIC,
            "page": "1",
            "offset": "200",
            "apikey": api_key,
        }
    )

    result = data.get("result")
    if not isinstance(result, list):
        return []
    return result


def format_short_address(wallet_address: str) -> str:
    return f"{wallet_address[:8]}...{wallet_address[-6:]}"


def build_reason(role: str, eth_amount: float, appearances: int) -> str:
    size_label = "sehr gross" if eth_amount >= 1000 else "gross"
    action = "Abfluss" if role == "sender" else "Zufluss"
    if appearances > 1:
        return f"{size_label}er {action}, mehrfach in grossen Transfers gesehen"
    return f"{size_label}er {action} in den letzten Blocks"


def parse_address_from_topic(topic: str) -> str:
    return f"0x{topic[-40:]}".lower()


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
        f"{signal['wallet_count']} grosse Wallets {direction_text} "
        f"{signal['symbol']} im selben Zeitfenster, daher {strength} Cluster."
    )


def parse_token_transfer_event(log: dict, token: dict) -> dict | None:
    topics = log.get("topics")
    data_hex = log.get("data")
    if not isinstance(topics, list) or len(topics) < 3 or not isinstance(data_hex, str):
        return None

    raw_amount = int(data_hex, 16)
    amount = raw_amount / 10 ** token["decimals"]
    timestamp = int(str(log.get("timeStamp", "0")), 16)

    return {
        "from": parse_address_from_topic(str(topics[1])),
        "to": parse_address_from_topic(str(topics[2])),
        "amount": amount,
        "timestamp": timestamp,
        "symbol": token["symbol"],
    }


def build_cluster_signals(token: dict, logs: list[dict]) -> list[dict]:
    grouped_signals: dict[tuple[str, str, int], dict] = {}

    for log in logs:
        event = parse_token_transfer_event(log, token)
        if event is None or event["amount"] < token["large_threshold"]:
            continue

        bucket_start = event["timestamp"] - (event["timestamp"] % SCAN_WINDOW_SECONDS)
        directional_events = [
            ("accumulation", event["to"]),
            ("distribution", event["from"]),
        ]

        for direction, wallet in directional_events:
            signal_key = (token["symbol"], direction, bucket_start)
            if signal_key not in grouped_signals:
                grouped_signals[signal_key] = {
                    "symbol": token["symbol"],
                    "direction": direction,
                    "wallets": set(),
                    "wallet_count": 0,
                    "time_window": format_window(event["timestamp"]),
                    "total_size": 0.0,
                    "event_count": 0,
                }

            grouped_signals[signal_key]["wallets"].add(wallet)
            grouped_signals[signal_key]["wallet_count"] = len(grouped_signals[signal_key]["wallets"])
            grouped_signals[signal_key]["total_size"] += event["amount"]
            grouped_signals[signal_key]["event_count"] += 1

    signals = []
    for signal in grouped_signals.values():
        if signal["wallet_count"] < MIN_CLUSTER_WALLETS:
            continue

        signal["explanation"] = build_signal_reason(signal)
        signal["wallets"] = list(signal["wallets"])
        signals.append(signal)

    return signals


def resolve_scan_targets(text: str) -> tuple[list[dict], str | None]:
    parts = text.split()
    if len(parts) == 1:
        return list(TRACKED_TOKENS.values()), None

    requested_token = parts[1].lower()
    if requested_token in UNSUPPORTED_TOKENS:
        return [], UNSUPPORTED_TOKENS[requested_token]

    for token in TRACKED_TOKENS.values():
        if requested_token in token["aliases"]:
            return [token], None

    supported_names = ", ".join(token["symbol"] for token in TRACKED_TOKENS.values())
    return [], f"Fehler: Token nicht bekannt. Unterstuetzt werden aktuell {supported_names}."


def rank_signals(signals: list[dict], prioritized_symbol: str | None) -> list[dict]:
    def sort_key(signal: dict) -> tuple:
        priority_bonus = 1 if prioritized_symbol and signal["symbol"] == prioritized_symbol else 0
        return (priority_bonus, signal["wallet_count"], signal["total_size"], signal["event_count"])

    return sorted(signals, key=sort_key, reverse=True)


def scan_whale_token_activity(text: str) -> str:
    api_key = get_etherscan_api_key()
    if not api_key:
        return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

    tokens_to_scan, target_error = resolve_scan_targets(text)
    if target_error:
        return target_error

    prioritized_symbol = None
    if len(tokens_to_scan) == 1:
        prioritized_symbol = tokens_to_scan[0]["symbol"]

    try:
        latest_block = fetch_latest_block_number()
        if latest_block is None:
            return "Fehler: Letzter Ethereum-Block konnte nicht gelesen werden."

        from_block = max(latest_block - SCAN_LOOKBACK_BLOCKS, 0)
        all_signals = []

        for token in tokens_to_scan:
            logs = fetch_token_transfer_logs(token["contract"], from_block, latest_block)
            token_signals = build_cluster_signals(token, logs)
            all_signals.extend(token_signals)

        if not all_signals:
            return (
                "Kein starkes Whale-Cluster gefunden. "
                "Das ist echte Onchain-Logik auf Transfer-Basis, aber noch kein DEX-Buy/Sell-Beweis."
            )

        ranked_signals = rank_signals(all_signals, prioritized_symbol)[:MAX_RESULTS]
        lines = [
            "Scan fertig. Starke Whale-Signale aus dem letzten kurzen Zeitfenster:"
        ]
        for index, signal in enumerate(ranked_signals, start=1):
            direction_text = (
                "accumulation" if signal["direction"] == "accumulation" else "distribution"
            )
            lines.append(
                f"{index}. {signal['symbol']} | {direction_text} | "
                f"{signal['wallet_count']} Wallets | {signal['time_window']} | "
                f"{signal['total_size']:.2f} {signal['symbol']} | {signal['explanation']}"
            )

        if prioritized_symbol:
            lines.append(f"Priorisiert: {prioritized_symbol}")
        else:
            lines.append("Standard-Tracking: ONDO, ETH, BTC, POL")

        lines.append(
            "Hinweis: accumulation/distribution basiert hier auf grossen Token-Transfers, "
            "nicht auf bestaetigten DEX-Buys oder -Sells."
        )
        return "\n".join(lines)
    except requests.RequestException:
        return "Fehler: Token-Scan ueber Etherscan ist fehlgeschlagen."
    except ValueError:
        return "Fehler: Etherscan hat ungueltige Token-Daten geliefert."


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
                "Schick mir eine Ethereum Wallet-Adresse und ich zeige dir "
                "ETH Guthaben plus letzte Transaktionen. Mit scan suche ich "
                "nach Whale-Clustern fuer ONDO, ETH, BTC oder POL."
            )
        }
    if "preis" in text:
        return {"response": "Kommt drauf an"}
    return {"response": "Noch nicht gelernt"}
