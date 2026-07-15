from __future__ import annotations

import copy
import threading
import time

from config.settings import (
    CACHE_POLICIES,
    COINGECKO_CIRCUIT_BREAKER_SECONDS,
    DEFAULT_CACHE_POLICY,
    MARKET_CONTEXT_CACHE_TTL_SECONDS,
    MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
    MARKET_PAGE_CACHE_TTL_SECONDS,
    MARKET_PAGE_STALE_TTL_SECONDS,
)
from models.domain_models import MarketContext
from sources.coingecko_source import CoinGeckoSource


class FreshCoinGeckoSource(CoinGeckoSource):
    """Request-local status plus policy-aware shared market caches."""

    _shared_cache: dict[str, tuple[float, MarketContext]] = {}
    _shared_page_cache: dict[
        tuple[int, int],
        tuple[float, float, list[dict]],
    ] = {}
    _circuit_until = 0.0
    _circuit_reason = ""
    _cache_lock = threading.RLock()

    def __init__(self, cache_policy: str = DEFAULT_CACHE_POLICY) -> None:
        super().__init__()
        if cache_policy not in CACHE_POLICIES:
            raise ValueError(
                f"Unsupported cache_policy '{cache_policy}'. "
                f"Allowed: {', '.join(sorted(CACHE_POLICIES))}."
            )
        self.cache_policy = cache_policy
        self.cache_hits = 0
        self.cache_misses = 0
        self.page_cache_hits = 0
        self.page_cache_misses = 0
        self.page_stale_fallbacks = 0
        self.circuit_breaker_hits = 0
        self.last_market_movers: list[dict] = []

    @classmethod
    def clear_shared_cache(cls) -> None:
        with cls._cache_lock:
            cls._shared_cache.clear()
            cls._shared_page_cache.clear()
            cls._circuit_until = 0.0
            cls._circuit_reason = ""

    def get_market_context(self, contract_address: str) -> MarketContext:
        key = contract_address.lower()
        now = time.monotonic()
        allow_reuse = self.cache_policy == "same_run_reuse"

        if allow_reuse:
            with self._cache_lock:
                cached = self._shared_cache.get(key)
                if cached is not None:
                    expires_at, context = cached
                    if expires_at > now:
                        self.cache_hits += 1
                        self.source_status["CoinGecko"] = (
                            "ok_cached" if context.available else "cached_unavailable"
                        )
                        return copy.deepcopy(context)
                    self._shared_cache.pop(key, None)

        self.cache_misses += 1
        self._cache.pop(key, None)
        context = super().get_market_context(key)
        ttl = (
            MARKET_CONTEXT_CACHE_TTL_SECONDS
            if context.available
            else MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS
        )

        with self._cache_lock:
            self._shared_cache[key] = (
                time.monotonic() + ttl,
                copy.deepcopy(context),
            )
        return context

    def get_market_page(self, page: int = 1, per_page: int = 100) -> list[dict]:
        key = (page, per_page)
        now = time.monotonic()
        stale_rows: list[dict] | None = None
        allow_fresh_reuse = self.cache_policy == "same_run_reuse"
        allow_stale = self.cache_policy != "audit_refresh"
        cls = type(self)

        with cls._cache_lock:
            cached = cls._shared_page_cache.get(key)
            if cached is not None:
                fresh_until, stale_until, rows = cached
                if allow_fresh_reuse and fresh_until > now:
                    self.page_cache_hits += 1
                    self.source_status["CoinGecko"] = "ok_cached"
                    return copy.deepcopy(rows)
                if allow_stale and stale_until > now:
                    stale_rows = rows
                elif stale_until <= now:
                    cls._shared_page_cache.pop(key, None)

            circuit_open = cls._circuit_until > now
            circuit_reason = cls._circuit_reason

        if circuit_open:
            self.circuit_breaker_hits += 1
            self.source_status["CoinGecko"] = f"circuit_open_{circuit_reason or 'temporary'}"
            if stale_rows is not None:
                self.page_stale_fallbacks += 1
                self.source_status["CoinGecko"] = f"stale_cache_{circuit_reason or 'temporary'}"
                return copy.deepcopy(stale_rows)
            return []

        self.page_cache_misses += 1
        rows = super().get_market_page(page=page, per_page=per_page)
        if rows:
            stored_rows = copy.deepcopy(rows)
            stored_at = time.monotonic()
            with cls._cache_lock:
                cls._shared_page_cache[key] = (
                    stored_at + MARKET_PAGE_CACHE_TTL_SECONDS,
                    stored_at + MARKET_PAGE_STALE_TTL_SECONDS,
                    stored_rows,
                )
                cls._circuit_until = 0.0
                cls._circuit_reason = ""
            return rows

        failure_kind = self.source_status.get("CoinGecko", "unavailable")
        if failure_kind in {"rate_limit", "temporary_http", "timeout", "connection"}:
            with cls._cache_lock:
                cls._circuit_until = time.monotonic() + COINGECKO_CIRCUIT_BREAKER_SECONDS
                cls._circuit_reason = failure_kind

        if stale_rows is not None:
            self.page_stale_fallbacks += 1
            self.source_status["CoinGecko"] = f"stale_cache_{failure_kind}"
            return copy.deepcopy(stale_rows)

        return []

    def get_market_movers(self, limit: int = 8) -> list[dict]:
        self.last_market_movers = super().get_market_movers(limit=limit)
        return self.last_market_movers

    def cache_diagnostics(self) -> dict[str, int | str | bool | float]:
        now = time.monotonic()
        cls = type(self)
        with cls._cache_lock:
            circuit_remaining = max(0.0, cls._circuit_until - now)
        return {
            "cache_policy": self.cache_policy,
            "contract_hits": self.cache_hits,
            "contract_misses": self.cache_misses,
            "contract_success_ttl_seconds": MARKET_CONTEXT_CACHE_TTL_SECONDS,
            "contract_negative_ttl_seconds": MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS,
            "market_page_hits": self.page_cache_hits,
            "market_page_misses": self.page_cache_misses,
            "market_page_stale_fallbacks": self.page_stale_fallbacks,
            "market_page_ttl_seconds": MARKET_PAGE_CACHE_TTL_SECONDS,
            "market_page_stale_ttl_seconds": MARKET_PAGE_STALE_TTL_SECONDS,
            "circuit_breaker_hits": self.circuit_breaker_hits,
            "circuit_open": circuit_remaining > 0,
            "circuit_remaining_seconds": round(circuit_remaining, 3),
        }
