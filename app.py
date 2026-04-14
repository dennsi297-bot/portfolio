import os
import re

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
SCAN_BLOCK_COUNT = 5
SCAN_THRESHOLDS = [100.0, 25.0, 10.0]
MAX_RESULTS = 5


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


def fetch_block_transactions(block_number: int) -> list[dict]:
    api_key = get_etherscan_api_key()
    if not api_key:
        return []

    data = call_etherscan(
        {
            "chainid": "1",
            "module": "proxy",
            "action": "eth_getBlockByNumber",
            "tag": hex(block_number),
            "boolean": "true",
            "apikey": api_key,
        }
    )

    result = data.get("result")
    if not isinstance(result, dict):
        return []

    transactions = result.get("transactions")
    if not isinstance(transactions, list):
        return []
    return transactions


def format_short_address(wallet_address: str) -> str:
    return f"{wallet_address[:8]}...{wallet_address[-6:]}"


def build_reason(role: str, eth_amount: float, appearances: int) -> str:
    size_label = "sehr gross" if eth_amount >= 1000 else "gross"
    action = "Abfluss" if role == "sender" else "Zufluss"
    if appearances > 1:
        return f"{size_label}er {action}, mehrfach in grossen Transfers gesehen"
    return f"{size_label}er {action} in den letzten Blocks"


def collect_wallet_scores(latest_block: int, min_interesting_eth: float) -> dict[tuple[str, str], dict]:
    wallet_scores: dict[tuple[str, str], dict] = {}

    for block_number in range(latest_block, latest_block - SCAN_BLOCK_COUNT, -1):
        transactions = fetch_block_transactions(block_number)
        for tx in transactions:
            if str(tx.get("input", "")) != "0x":
                continue

            value_hex = tx.get("value")
            from_address = str(tx.get("from", ""))
            to_address = str(tx.get("to", ""))

            if not value_hex or not from_address or not to_address:
                continue

            value_eth = int(value_hex, 16) / 10**18
            if value_eth < min_interesting_eth:
                continue

            sender_key = (from_address, "sender")
            receiver_key = (to_address, "receiver")

            for wallet_key, role in ((sender_key, "sender"), (receiver_key, "receiver")):
                if wallet_key not in wallet_scores:
                    wallet_scores[wallet_key] = {
                        "address": wallet_key[0],
                        "role": role,
                        "max_eth": value_eth,
                        "count": 1,
                    }
                else:
                    wallet_scores[wallet_key]["max_eth"] = max(
                        wallet_scores[wallet_key]["max_eth"], value_eth
                    )
                    wallet_scores[wallet_key]["count"] += 1

    return wallet_scores


def scan_recent_eth_activity() -> str:
    api_key = get_etherscan_api_key()
    if not api_key:
        return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

    try:
        latest_block = fetch_latest_block_number()
        if latest_block is None:
            return "Fehler: Letzter Ethereum-Block konnte nicht gelesen werden."

        chosen_threshold = SCAN_THRESHOLDS[-1]
        wallet_scores: dict[tuple[str, str], dict] = {}
        for threshold in SCAN_THRESHOLDS:
            wallet_scores = collect_wallet_scores(latest_block, threshold)
            chosen_threshold = threshold
            if wallet_scores:
                break

        if not wallet_scores:
            return "Keine interessanten grossen ETH-Transfers in den letzten Blocks gefunden."

        ranked_wallets = sorted(
            wallet_scores.values(),
            key=lambda item: (item["max_eth"], item["count"]),
            reverse=True,
        )[:MAX_RESULTS]

        lines = [
            (
                f"Scan fertig. Interessante Wallets aus den letzten "
                f"{SCAN_BLOCK_COUNT} Blocks ab {chosen_threshold:.0f} ETH:"
            )
        ]
        for index, wallet in enumerate(ranked_wallets, start=1):
            role_text = "Sender" if wallet["role"] == "sender" else "Empfaenger"
            reason = build_reason(wallet["role"], wallet["max_eth"], wallet["count"])
            lines.append(
                f"{index}. {wallet['address']} | {wallet['max_eth']:.2f} ETH | "
                f"{role_text} | {reason}"
            )
        return "\n".join(lines)
    except requests.RequestException:
        return "Fehler: Ethereum-Scan ueber Etherscan ist fehlgeschlagen."
    except ValueError:
        return "Fehler: Etherscan hat ungueltige Daten fuer den Scan geliefert."


@app.get("/")
def read_root():
    return {"message": "Bot laeuft"}


@app.post("/message")
def handle_message(msg: Message):
    original_text = msg.text.strip()
    text = original_text.lower()

    if is_ethereum_wallet(original_text):
        return {"response": format_wallet_summary(original_text)}
    if text == "scan":
        return {"response": scan_recent_eth_activity()}

    if "hallo" in text:
        return {"response": "Hey"}
    if "hilfe" in text:
        return {
            "response": (
                "Schick mir eine Ethereum Wallet-Adresse und ich zeige dir "
                "ETH Guthaben plus letzte Transaktionen. Mit scan suche ich "
                "automatisch nach grossen ETH-Bewegungen."
            )
        }
    if "preis" in text:
        return {"response": "Kommt drauf an"}
    return {"response": "Noch nicht gelernt"}
