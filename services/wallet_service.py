from sources.etherscan_source import EtherscanSource
from utils.http_client import ExternalAPIError


class WalletService:
    """Direct wallet utilities. Real logic backed by Etherscan."""

    def __init__(self, source: EtherscanSource) -> None:
        self.source = source

    def get_wallet_snapshot(self, wallet_address: str, limit: int = 3) -> dict:
        """Return stable machine-readable wallet data for OpenClaw and text clients."""
        try:
            balance_text = self.source.get_eth_balance(wallet_address)
        except ExternalAPIError as exc:
            return {
                "ok": False,
                "partial": False,
                "wallet": wallet_address,
                "balance_eth": None,
                "balance_text": None,
                "transactions": [],
                "error": {"source": exc.source, "kind": exc.kind, "message": exc.message},
            }

        if balance_text.startswith("Fehler:"):
            return {
                "ok": False,
                "partial": False,
                "wallet": wallet_address,
                "balance_eth": None,
                "balance_text": balance_text,
                "transactions": [],
                "error": {"source": "Etherscan", "kind": "api_error", "message": balance_text},
            }

        balance_eth = self._parse_balance_eth(balance_text)
        transaction_error = None
        try:
            recent_transactions = self.source.get_wallet_transactions(wallet_address, limit=limit)
        except ExternalAPIError as exc:
            recent_transactions = []
            transaction_error = {
                "source": exc.source,
                "kind": exc.kind,
                "message": exc.message,
            }

        transactions = []
        for tx in recent_transactions:
            transactions.append(
                {
                    "direction": self._format_tx_direction(wallet_address, tx),
                    "value_eth": self._value_eth(tx),
                    "hash": str(tx.get("hash", "")),
                    "from": str(tx.get("from", "")),
                    "to": str(tx.get("to", "")),
                    "timestamp": tx.get("timeStamp"),
                    "is_error": str(tx.get("isError", "0")) == "1",
                }
            )

        return {
            "ok": True,
            "partial": transaction_error is not None,
            "wallet": wallet_address,
            "balance_eth": balance_eth,
            "balance_text": balance_text,
            "transactions": transactions,
            "transaction_error": transaction_error,
        }

    def format_wallet_summary(self, wallet_address: str) -> str:
        return self.format_wallet_snapshot(self.get_wallet_snapshot(wallet_address))

    @staticmethod
    def format_wallet_snapshot(snapshot: dict) -> str:
        if not snapshot.get("ok"):
            error = snapshot.get("error") or {}
            kind = error.get("kind")
            if kind:
                return f"Fehler: Etherscan konnte gerade nicht erreicht werden ({kind})."
            return str(snapshot.get("balance_text") or "Fehler: Wallet-Daten konnten nicht geladen werden.")

        lines = [
            f"Wallet {snapshot.get('wallet', '')}",
            f"ETH Guthaben: {snapshot.get('balance_text') or 'n/a'}",
            "Letzte Transaktionen:",
        ]
        transactions = snapshot.get("transactions") or []
        if not transactions:
            lines[-1] = "Letzte Transaktionen: Keine Daten gefunden."
        else:
            for tx in transactions:
                tx_hash = str(tx.get("hash", ""))[:10]
                lines.append(
                    f"- {tx.get('direction', 'Bewegung')}: "
                    f"{float(tx.get('value_eth') or 0.0):.6f} ETH | Hash {tx_hash}..."
                )
        if snapshot.get("partial"):
            lines.append("Hinweis: Guthaben geladen, Transaktionsliste momentan unvollstaendig.")
        return "\n".join(lines)

    @staticmethod
    def _parse_balance_eth(balance_text: str) -> float | None:
        try:
            return float(balance_text.split()[0])
        except (AttributeError, IndexError, TypeError, ValueError):
            return None

    @staticmethod
    def _value_eth(tx: dict) -> float:
        try:
            return int(tx.get("value", "0")) / 10**18
        except (TypeError, ValueError):
            return 0.0

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
