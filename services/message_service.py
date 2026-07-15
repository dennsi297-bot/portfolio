from services.signal_engine import WhaleSignalEngine
from services.wallet_service import WalletService
from utils.text_utils import is_ethereum_wallet


class MessageService:
    """Small orchestration layer between API routes and domain services."""

    def __init__(self, wallet_service: WalletService, signal_engine: WhaleSignalEngine) -> None:
        self.wallet_service = wallet_service
        self.signal_engine = signal_engine

    def handle_message(self, text: str) -> str:
        original_text = text.strip()
        lowered_text = original_text.lower()

        if is_ethereum_wallet(original_text):
            return self.wallet_service.format_wallet_summary(original_text)
        if lowered_text.startswith("scan"):
            response = self.signal_engine.scan(lowered_text)
            return self._append_freshness_warning(response)
        if "hallo" in lowered_text:
            return "Hey"
        if "hilfe" in lowered_text:
            return (
                "Schick mir eine Ethereum Wallet-Adresse fuer den Direktcheck. "
                "Mit scan suche ich breit nach Whale-Clustern in Ethereum ERC-20 Transfers."
            )
        if "preis" in lowered_text:
            return "Kommt drauf an"
        return "Noch nicht gelernt"

    def _append_freshness_warning(self, response: str) -> str:
        market_source = getattr(self.signal_engine, "market_source", None)
        statuses = getattr(market_source, "source_status", {})
        stale = any(
            str(status).startswith("stale_cache_")
            or str(status).startswith("circuit_open_")
            for status in statuses.values()
        )
        if not stale:
            return response
        return "\n".join(
            [
                response,
                "QUALITY GUARD: Markt-Kontext ist stale/degraded.",
                "Diese Daten duerfen keinen neuen Trend, kein actionable Signal und keine starke Confluence bestaetigen.",
            ]
        )
