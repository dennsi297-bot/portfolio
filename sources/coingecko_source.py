from config.settings import COINGECKO_BASE_URL, get_coingecko_api_key
from models.domain_models import MarketContext
from utils.http_client import ExternalAPIError, get_json_with_retry


class CoinGeckoSource:
    """Public market-data source. Used for enrichment, market movers and rotation mode."""

    DEXSCREENER_BASE_URL = "https://api.dexscreener.com"

    def __init__(self) -> None:
        self._cache: dict[str, MarketContext] = {}
        self.source_status: dict[str, str] = {
            "CoinGecko": "not_used",
            "DexScreener": "not_used",
        }
        self.last_errors: list[str] = []

    def reset_status(self) -> None:
        self.source_status = {
            "CoinGecko": "not_used",
            "DexScreener": "not_used",
        }
        self.last_errors = []

    def _mark_ok(self, source: str) -> None:
        self.source_status[source] = "ok"

    def _mark_error(self, exc: ExternalAPIError) -> None:
        self.source_status[exc.source] = exc.kind
        self.last_errors.append(str(exc))

    def get_market_context(self, contract_address: str) -> MarketContext:
        contract_address = contract_address.lower()
        if contract_address in self._cache:
            return self._cache[contract_address]

        try:
            payload = get_json_with_retry(
                f"{COINGECKO_BASE_URL}/coins/ethereum/contract/{contract_address}",
                source="CoinGecko",
                headers=self._build_headers(),
                params={
                    "localization": "false",
                    "tickers": "false",
                    "market_data": "true",
                    "community_data": "false",
                    "developer_data": "false",
                    "sparkline": "false",
                },
                timeout=12,
                retries=2,
            )
            self._mark_ok("CoinGecko")
            if not isinstance(payload, dict):
                raise ExternalAPIError("CoinGecko", "invalid_payload", "Response was not an object", 1)

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
        except ExternalAPIError as exc:
            self._mark_error(exc)
            if "HTTP 404" in exc.message:
                context = MarketContext(
                    available=False,
                    limitation="CoinGecko mapping fuer diesen Contract nicht gefunden.",
                )
            else:
                context = MarketContext(
                    available=False,
                    limitation=f"CoinGecko Markt-Kontext momentan nicht erreichbar ({exc.kind}).",
                )

        self._cache[contract_address] = context
        return context

    def get_market_page(self, page: int = 1, per_page: int = 100) -> list[dict]:
        """Top market coins with 24h/7d performance for rotation mode."""
        try:
            payload = get_json_with_retry(
                f"{COINGECKO_BASE_URL}/coins/markets",
                source="CoinGecko",
                headers=self._build_headers(),
                params={
                    "vs_currency": "usd",
                    "order": "market_cap_desc",
                    "per_page": per_page,
                    "page": page,
                    "sparkline": "false",
                    "price_change_percentage": "24h,7d",
                },
                timeout=14,
                retries=2,
            )
            self._mark_ok("CoinGecko")
        except ExternalAPIError as exc:
            self._mark_error(exc)
            return []

        if not isinstance(payload, list):
            self.source_status["CoinGecko"] = "invalid_payload"
            return []

        rows: list[dict] = []
        for coin in payload:
            if not isinstance(coin, dict):
                continue
            symbol = str(coin.get("symbol", "")).upper()
            if not symbol:
                continue
            rows.append(
                {
                    "name": coin.get("name") or symbol,
                    "symbol": symbol,
                    "price": self._safe_number(coin.get("current_price")),
                    "change_24h": self._safe_number(coin.get("price_change_percentage_24h")),
                    "change_7d": self._safe_number(coin.get("price_change_percentage_7d_in_currency")),
                    "volume_24h": self._safe_number(coin.get("total_volume")),
                    "market_cap": self._safe_number(coin.get("market_cap")),
                    "rank": coin.get("market_cap_rank") if isinstance(coin.get("market_cap_rank"), int) else None,
                    "source": "CoinGecko",
                }
            )
        return rows

    def get_market_movers(self, limit: int = 8) -> list[dict]:
        movers = self._get_coingecko_market_movers(limit=limit)
        if movers:
            return movers
        return self._get_dexscreener_boosted_movers(limit=limit)

    def _get_coingecko_market_movers(self, limit: int = 8) -> list[dict]:
        rows = self.get_market_page(page=1, per_page=100)
        cleaned: list[dict] = []
        for coin in rows:
            change_24h = self._safe_number(coin.get("change_24h"))
            if change_24h is None:
                continue
            cleaned.append(
                {
                    **coin,
                    "source": "CoinGecko",
                    "note": "price-volume mover",
                    "chain": "multi",
                    "token_address": str(coin.get("symbol", "")).lower(),
                }
            )

        cleaned.sort(key=lambda item: (item.get("change_24h") or -999, item.get("volume_24h") or 0), reverse=True)
        return self._dedupe_movers(cleaned)[:limit]

    def _get_dexscreener_boosted_movers(self, limit: int = 8) -> list[dict]:
        try:
            boosted_payload = get_json_with_retry(
                f"{self.DEXSCREENER_BASE_URL}/token-boosts/top/v1",
                source="DexScreener",
                timeout=12,
                retries=2,
            )
            self._mark_ok("DexScreener")
        except ExternalAPIError as exc:
            self._mark_error(exc)
            return []

        if not isinstance(boosted_payload, list):
            self.source_status["DexScreener"] = "invalid_payload"
            return []

        addresses_by_chain: dict[str, list[str]] = {}
        for item in boosted_payload[:30]:
            if not isinstance(item, dict):
                continue
            chain_id = str(item.get("chainId", "")).strip()
            token_address = str(item.get("tokenAddress", "")).strip()
            if not chain_id or not token_address:
                continue
            addresses_by_chain.setdefault(chain_id, []).append(token_address)

        pair_rows: list[dict] = []
        for chain_id, addresses in addresses_by_chain.items():
            chunk = addresses[:30]
            if not chunk:
                continue
            try:
                pairs_payload = get_json_with_retry(
                    f"{self.DEXSCREENER_BASE_URL}/tokens/v1/{chain_id}/{','.join(chunk)}",
                    source="DexScreener",
                    timeout=12,
                    retries=2,
                )
                self._mark_ok("DexScreener")
            except ExternalAPIError as exc:
                self._mark_error(exc)
                continue

            if not isinstance(pairs_payload, list):
                self.source_status["DexScreener"] = "invalid_payload"
                continue
            for pair in pairs_payload:
                parsed = self._parse_dex_pair(pair)
                if parsed:
                    pair_rows.append(parsed)

        pair_rows.sort(key=lambda item: (item.get("boosts") or 0, item.get("change_24h") or -999, item.get("volume_24h") or 0), reverse=True)
        return self._dedupe_movers(pair_rows)[:limit]

    def _parse_dex_pair(self, pair: dict) -> dict | None:
        if not isinstance(pair, dict):
            return None
        base_token = pair.get("baseToken") if isinstance(pair.get("baseToken"), dict) else {}
        symbol = str(base_token.get("symbol", "")).upper()
        name = base_token.get("name") or symbol
        token_address = str(base_token.get("address", "")).strip()
        if not symbol:
            return None
        volume = pair.get("volume") if isinstance(pair.get("volume"), dict) else {}
        price_change = pair.get("priceChange") if isinstance(pair.get("priceChange"), dict) else {}
        boosts = pair.get("boosts") if isinstance(pair.get("boosts"), dict) else {}
        return {
            "name": name,
            "symbol": symbol,
            "price": self._safe_float_string(pair.get("priceUsd")),
            "change_24h": self._safe_number(price_change.get("h24")),
            "change_7d": None,
            "volume_24h": self._safe_number(volume.get("h24")),
            "rank": None,
            "market_cap": self._safe_number(pair.get("marketCap")) or self._safe_number(pair.get("fdv")),
            "source": "DexScreener",
            "note": "boosted/trending token fallback",
            "chain": pair.get("chainId"),
            "boosts": self._safe_number(boosts.get("active")),
            "token_address": token_address,
            "pair_url": pair.get("url"),
        }

    @staticmethod
    def _dedupe_movers(movers: list[dict]) -> list[dict]:
        best_by_key: dict[str, dict] = {}
        for mover in movers:
            symbol = str(mover.get("symbol", "")).upper()
            chain = str(mover.get("chain", "")).lower()
            token_address = str(mover.get("token_address", "")).lower()
            key = token_address or f"{chain}:{symbol}:{str(mover.get('name', '')).lower()}"
            current = best_by_key.get(key)
            if current is None:
                best_by_key[key] = mover
                continue
            current_score = (current.get("boosts") or 0, current.get("change_24h") or -999, current.get("volume_24h") or 0)
            mover_score = (mover.get("boosts") or 0, mover.get("change_24h") or -999, mover.get("volume_24h") or 0)
            if mover_score > current_score:
                best_by_key[key] = mover
        return list(best_by_key.values())

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
    def _safe_float_string(value: object) -> float | None:
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            try:
                return float(value)
            except ValueError:
                return None
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
