from __future__ import annotations

import threading
import time

from config.settings import (
    MARKET_CONTEXT_CACHE_TTL_SECONDS,
    MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
)
from models.domain_models import MarketContext
from sources.coingecko_source import CoinGeckoSource


class FreshCoinGeckoSource(CoinGeckoSource):
    """Request-local source state plus a process-wide bounded-TTL market cache.

    The original source cached MarketContext forever inside one process. That could
    keep stale prices or temporary failures alive until a Render restart. This class
    shares only immutable cache results, while status/error fields remain per request.
    """

    _shared_cache: dict[str, tuple[float, MarketContext]] = {}
    _cache_lock = threading.RLock()

    def __init__(self) -> None:
        super().__init__()
        self.cache_hits = 0
        self.cache_misses = 0
        self.last_market_movers: list[dict] = []

    @classmethod
    def clear_shared_cache(cls) -> None:
        with cls._cache_lock:
            cls._shared_cache.clear()

    def get_market_context(self, contract_address: str) -> MarketContext:
        key = contract_address.lower()
        now = time.monotonic()

        with self._cache_lock:
            cached = self._shared_cache.get(key)
            if cached is not None:
                expires_at, context = cached
                if expires_at > now:
                    self.cache_hits += 1
                    self.source_status["CoinGecko"] = "ok"
                    return context
                self._shared_cache.pop(key, None)

        self.cache_misses += 1
        # Prevent the parent instance cache from bypassing our TTL policy.
        self._cache.pop(key, None)
        context = super().get_market_context(key)
        ttl = (
            MARKET_CONTEXT_CACHE_TTL_SECONDS
            if context.available
            else MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS
        )

        with self._cache_lock:
            self._shared_cache[key] = (now + ttl, context)
        return context

    def get_market_movers(self, limit: int = 8) -> list[dict]:
        self.last_market_movers = super().get_market_movers(limit=limit)
        return self.last_market_movers

    def cache_diagnostics(self) -> dict[str, int]:
        return {
            "hits": self.cache_hits,
            "misses": self.cache_misses,
            "success_ttl_seconds": MARKET_CONTEXT_CACHE_TTL_SECONDS,
            "negative_ttl_seconds": MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
        }
