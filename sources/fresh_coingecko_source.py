from __future__ import annotations

import copy
import threading
import time

from config.settings import (
    MARKET_CONTEXT_CACHE_TTL_SECONDS,
    MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
    MARKET_PAGE_CACHE_TTL_SECONDS,
    MARKET_PAGE_STALE_TTL_SECONDS,
)
from models.domain_models import MarketContext
from sources.coingecko_source import CoinGeckoSource


class FreshCoinGeckoSource(CoinGeckoSource):
    """Request-local source state plus bounded shared market caches.

    Contract context uses a short TTL. Broad market pages are shared across market,
    rotation and confluence requests so one OpenClaw cycle does not repeatedly spend
    the same CoinGecko quota. A recent stale page may be used only after a live refresh
    fails; the source status then exposes the degraded fallback explicitly.
    """

    _shared_cache: dict[str, tuple[float, MarketContext]] = {}
    _shared_page_cache: dict[
        tuple[int, int],
        tuple[float, float, list[dict]],
    ] = {}
    _cache_lock = threading.RLock()

    def __init__(self) -> None:
        super().__init__()
        self.cache_hits = 0
        self.cache_misses = 0
        self.page_cache_hits = 0
        self.page_cache_misses = 0
        self.page_stale_fallbacks = 0
        self.last_market_movers: list[dict] = []

    @classmethod
    def clear_shared_cache(cls) -> None:
        with cls._cache_lock:
            cls._shared_cache.clear()
            cls._shared_page_cache.clear()

    def get_market_context(self, contract_address: str) -> MarketContext:
        key = contract_address.lower()
        now = time.monotonic()

        with self._cache_lock:
            cached = self._shared_cache.get(key)
            if cached is not None:
                expires_at, context = cached
                if expires_at > now:
                    self.cache_hits += 1
                    self.source_status["CoinGecko"] = (
                        "ok_cached" if context.available else "cached_unavailable"
                    )
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
            self._shared_cache[key] = (time.monotonic() + ttl, context)
        return context

    def get_market_page(self, page: int = 1, per_page: int = 100) -> list[dict]:
        key = (page, per_page)
        now = time.monotonic()
        stale_rows: list[dict] | None = None

        with self._cache_lock:
            cached = self._shared_page_cache.get(key)
            if cached is not None:
                fresh_until, stale_until, rows = cached
                if fresh_until > now:
                    self.page_cache_hits += 1
                    self.source_status["CoinGecko"] = "ok_cached"
                    return copy.deepcopy(rows)
                if stale_until > now:
                    stale_rows = rows
                else:
                    self._shared_page_cache.pop(key, None)

        self.page_cache_misses += 1
        rows = super().get_market_page(page=page, per_page=per_page)
        if rows:
            stored_rows = copy.deepcopy(rows)
            stored_at = time.monotonic()
            with self._cache_lock:
                self._shared_page_cache[key] = (
                    stored_at + MARKET_PAGE_CACHE_TTL_SECONDS,
                    stored_at + MARKET_PAGE_STALE_TTL_SECONDS,
                    stored_rows,
                )
            return rows

        if stale_rows is not None:
            self.page_stale_fallbacks += 1
            failure_kind = self.source_status.get("CoinGecko", "unavailable")
            self.source_status["CoinGecko"] = f"stale_cache_{failure_kind}"
            return copy.deepcopy(stale_rows)

        return []

    def get_market_movers(self, limit: int = 8) -> list[dict]:
        self.last_market_movers = super().get_market_movers(limit=limit)
        return self.last_market_movers

    def cache_diagnostics(self) -> dict[str, int]:
        return {
            "contract_hits": self.cache_hits,
            "contract_misses": self.cache_misses,
            "contract_success_ttl_seconds": MARKET_CONTEXT_CACHE_TTL_SECONDS,
            "contract_negative_ttl_seconds": MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
            "market_page_hits": self.page_cache_hits,
            "market_page_misses": self.page_cache_misses,
            "market_page_stale_fallbacks": self.page_stale_fallbacks,
            "market_page_ttl_seconds": MARKET_PAGE_CACHE_TTL_SECONDS,
            "market_page_stale_ttl_seconds": MARKET_PAGE_STALE_TTL_SECONDS,
        }
