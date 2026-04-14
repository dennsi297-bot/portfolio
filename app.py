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


def is_ethereum_wallet(text: str) -> bool:
    return bool(WALLET_PATTERN.fullmatch(text.strip()))


def fetch_eth_balance(wallet_address: str) -> str:
    api_key = os.getenv("ETHERSCAN_API_KEY")
    if not api_key:
        return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

    try:
        response = requests.get(
            "https://api.etherscan.io/v2/api",
            params={
                "chainid": "1",
                "module": "account",
                "action": "balance",
                "address": wallet_address,
                "tag": "latest",
                "apikey": api_key,
            },
            timeout=10,
        )
        response.raise_for_status()
        data = response.json()
    except requests.RequestException:
        return "Fehler: Etherscan konnte gerade nicht erreicht werden."

    if data.get("status") != "1" or "result" not in data:
        message = data.get("message") or "Unbekannter API-Fehler."
        return f"Fehler: {message}"

    balance_wei = int(data["result"])
    balance_eth = balance_wei / 10**18
    return f"ETH Guthaben fuer {wallet_address}: {balance_eth:.6f} ETH"


@app.get("/")
def read_root():
    return {"message": "Bot laeuft"}


@app.post("/message")
def handle_message(msg: Message):
    original_text = msg.text.strip()
    text = original_text.lower()

    if is_ethereum_wallet(original_text):
        return {"response": fetch_eth_balance(original_text)}

    if "hallo" in text:
        return {"response": "Hey"}
    if "preis" in text:
        return {"response": "Kommt drauf an"}
    return {"response": "Noch nicht gelernt"}
