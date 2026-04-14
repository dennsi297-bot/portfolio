import requests

from sources.etherscan_source import EtherscanSource


class WalletService:
    """Direct wallet utilities. Real logic backed by Etherscan."""

    def __init__(self, source: EtherscanSource) -> None:
        self.source = source

    def format_wallet_summary(self, wallet_address: str) -> str:
        try:
            balance_text = self.source.get_eth_balance(wallet_address)
        except requests.RequestException:
            return "Fehler: Etherscan konnte gerade nicht erreicht werden."

        if balance_text.startswith("Fehler:"):
            return balance_text

        try:
            recent_transactions = self.source.get_wallet_transactions(wallet_address, limit=3)
        except requests.RequestException:
            recent_transactions = []

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
            direction = self._format_tx_direction(wallet_address, tx)
            value_eth = int(tx.get("value", "0")) / 10**18
            tx_hash = str(tx.get("hash", ""))[:10]
            lines.append(f"- {direction}: {value_eth:.6f} ETH | Hash {tx_hash}...")

        return "\n".join(lines)

    @staticmethod
    def _format_tx_direction(wallet_address: str, tx: dict) -> str:
        from_address = str(tx.get("from", "")).lower()
        to_address = str(tx.get("to", "")).lower()
        wallet_lower = wallet_address.lower()

        if to_address == wallet_lower:
            return "Eingang"
        if from_address == wallet_lower:
            return "Ausgang"
        return "Bewegung"
