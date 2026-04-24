import requests

from config.settings import COINGECKO_BASE_URL, get_coingecko_api_key
from models.domain_models import MarketContext


class CoinGeckoSource:
    """Public market-data source. Used for enrichment and separate market mover mode."""

    def __init__(self) -> None:
        self._cache: dict[str, MarketContext] = {}

    def get_market_context(self, contract_address: str) -> MarketContext:
        contract_address = contract_address.lower()
        if contract_address in self._cache:
            return self._cache[contract_address]

        try:
            response = requests.get(
                f"{COINGECKO_BASE_URL}/coins/ethereum/contract/{contract_address}",
                headers=self._build_headers(),
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                timeout=10,
            )
            if response.status_code == 404:
                context = MarketContext(
                    available=False,
                    limitation="CoinGecko mapping fuer diesen Contract nicht gefunden.",
                )
                self._cache[contract_address] = context
                return context

            response.raise_for_status()
            payload = response.json()
            context = MarketContext(
                token_name=payload.get("name"),
                token_symbol=str(payload.get("symbol", "")).upper() or None,
                market_cap_rank=payload.get("market_cap_rank"),
                current_price_usd=self._safe_nested_number(payload, "market_data", "current_price", "usd"),
                volume_24h_usd=self._safe_nested_number(payload, "market_data", "total_volume", "usd"),
                price_change_24h=self._safe_nested_number(payload, "market_data", "price_change_percentage_24h"),
                categories=self._safe_categories(payload.get("categories")),
                market_profile=self._classify_profile(payload.get("market_cap_rank")),
                available=True,
            )
        except requests.RequestException:
            context = MarketContext(
                available=False,
                limitation="CoinGecko Markt-Kontext momentan nicht erreichbar.",
            )

        self._cache[contract_address] = context
        return context

    def get_market_movers(self, limit: int = 8) -> list[dict]:
        """
        Separate price/volume mover scan.
        This does not replace the whale scan. It only answers: what is moving now?
        """
        try:
            response = requests.get(
                f"{COINGECKO_BASE_URL}/coins/markets",
                headers=self._build_headers(),
                params={
                    "vs_currency": "usd",
                    "order": "volume_desc",
                    "per_page": 100,
                    "page": 1,
                    "sparkline": "false",
                    "price_change_percentage": "1h,24h,7d",
                },
                timeout=12,
            )
            response.raise_for_status()
            payload = response.json()
        except requests.RequestException:
            return []

        if not isinstance(payload, list):
            return []

        cleaned: list[dict] = []
        for coin in payload:
            if not isinstance(coin, dict):
                continue
            symbol = str(coin.get("symbol", "")).upper()
            if not symbol:
                continue
            change_24h = self._safe_number(coin.get("price_change_percentage_24h"))
            volume = self._safe_number(coin.get("total_volume"))
            price = self._safe_number(coin.get("current_price"))
            rank = coin.get("market_cap_rank")
            if change_24h is None:
                continue
            cleaned.append(
                {
                    "name": coin.get("name") or symbol,
                    "symbol": symbol,
                    "price": price,
                    "change_24h": change_24h,
                    "volume_24h": volume,
                    "rank": rank if isinstance(rank, int) else None,
                    "market_cap": self._safe_number(coin.get("market_cap")),
                }
            )

        # High positive movers first. Volume is secondary so pure illiquid junk is less dominant.
        cleaned.sort(
            key=lambda item: (
                item.get("change_24h") or -999,
                item.get("volume_24h") or 0,
            ),
            reverse=True,
        )
        return cleaned[:limit]

    @staticmethod
    def _build_headers() -> dict:
        api_key = get_coingecko_api_key()
        if not api_key:
            return {}
        return {"x-cg-demo-api-key": api_key}

    @staticmethod
    def _safe_nested_number(payload: dict, *keys: str) -> float | None:
        current = payload
        for key in keys:
            if not isinstance(current, dict) or key not in current:
                return None
            current = current[key]
        return CoinGeckoSource._safe_number(current)

    @staticmethod
    def _safe_number(value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        return None

    @staticmethod
    def _safe_categories(categories: object) -> list[str] | None:
        if isinstance(categories, list):
            return [str(item) for item in categories[:4] if item]
        return None

    @staticmethod
    def _classify_profile(rank: object) -> str:
        if not isinstance(rank, int):
            return "obscure"
        if rank <= 50:
            return "major"
        if rank <= 250:
            return "mid-cap"
        return "obscure"
