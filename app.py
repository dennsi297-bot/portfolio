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
    api_key = os.getenv("ETHERSCAN_API_KEY")
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


@app.get("/")
def read_root():
    return {"message": "Bot laeuft"}


@app.post("/message")
def handle_message(msg: Message):
    original_text = msg.text.strip()
    text = original_text.lower()

    if is_ethereum_wallet(original_text):
        return {"response": format_wallet_summary(original_text)}

    if "hallo" in text:
        return {"response": "Hey"}
    if "hilfe" in text:
        return {
            "response": (
                "Schick mir eine Ethereum Wallet-Adresse und ich zeige dir "
                "ETH Guthaben plus letzte Transaktionen."
            )
        }
    if "preis" in text:
        return {"response": "Kommt drauf an"}
    return {"response": "Noch nicht gelernt"}
