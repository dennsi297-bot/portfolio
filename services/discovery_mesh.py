from __future__ import annotations

from collections import defaultdict
from typing import Any

from config.settings import (
    BASE_CONTEXT_SYMBOLS,
    DISCOVERY_COINGECKO_PAGES,
    DISCOVERY_CONTRACT_RESOLUTION_LIMIT,
    DISCOVERY_COINGECKO_PER_PAGE,
    DISCOVERY_DEX_LIMIT,
    DISCOVERY_TOP_CANDIDATES,
    STABLECOIN_SYMBOLS,
)
from sources.fresh_coingecko_source import FreshCoinGeckoSource


class DiscoveryMeshService:
    """Broad market discovery layer.

    This service deliberately separates market discovery from whale confirmation.
    It scans a broader CoinGecko universe and DexScreener in parallel, scores
    short-horizon acceleration, and annotates whether a candidate can be probed
    by the Ethereum whale scanner.
    """

    def __init__(self, market_source: FreshCoinGeckoSource) -> None:
        self.market_source = market_source

    def scan(
        self,
        *,
        coingecko_pages: int = DISCOVERY_COINGECKO_PAGES,
        coingecko_per_page: int = DISCOVERY_COINGECKO_PER_PAGE,
        dex_limit: int = DISCOVERY_DEX_LIMIT,
        top_n: int = DISCOVERY_TOP_CANDIDATES,
    ) -> dict[str, Any]:
        market_rows: list[dict[str, Any]] = []
        completed_pages: list[int] = []

        for page in range(1, max(1, coingecko_pages) + 1):
            rows = self.market_source.get_market_page(
                page=page,
                per_page=coingecko_per_page,
            )
            if not rows:
                break
            completed_pages.append(page)
            market_rows.extend(rows)

        # DexScreener is intentionally queried even when CoinGecko succeeds.
        dex_rows = self.market_source.get_dexscreener_discovery(limit=dex_limit)

        normalized: list[dict[str, Any]] = []
        normalized.extend(self._from_coingecko(row) for row in market_rows)
        normalized.extend(self._from_dex(row) for row in dex_rows)
        normalized = [
            row
            for row in normalized
            if row
            and str(row.get("symbol", "")).upper()
            not in (STABLECOIN_SYMBOLS | BASE_CONTEXT_SYMBOLS)
        ]

        sources_by_symbol: dict[str, set[str]] = defaultdict(set)
        for row in normalized:
            symbol = str(row.get("symbol", "")).upper()
            source = str(row.get("source", ""))
            if symbol and source:
                sources_by_symbol[symbol].add(source)

        for row in normalized:
            symbol = str(row.get("symbol", "")).upper()
            row["source_consensus"] = len(sources_by_symbol.get(symbol, set())) or 1
            row["discovery_score"] = self._score(row)
            row["status"] = self._status(row)

        deduped = self._dedupe(normalized)
        deduped.sort(
            key=lambda row: (
                float(row.get("discovery_score") or 0.0),
                float(row.get("change_1h") or 0.0),
                float(row.get("change_24h") or 0.0),
                float(row.get("volume_24h") or 0.0),
            ),
            reverse=True,
        )

        resolutions = 0
        for row in deduped:
            if resolutions >= max(0, DISCOVERY_CONTRACT_RESOLUTION_LIMIT):
                break
            if row.get("source") != "CoinGecko" or row.get("token_address"):
                continue
            coin_id = str(row.get("coin_id") or "")
            if not coin_id or not hasattr(self.market_source, "get_ethereum_contract"):
                continue
            resolutions += 1
            contract = self.market_source.get_ethereum_contract(coin_id)
            if contract:
                row["chain"] = "ethereum"
                row["token_address"] = contract

        for row in deduped:
            row["whale_status"] = self._initial_whale_status(row)
            row["whale_reason"] = self._initial_whale_reason(row)

        return {
            "ok": bool(market_rows or dex_rows),
            "mode": "discovery",
            "decision_eligible": False,
            "coverage": {
                "coingecko_requested_pages": max(1, coingecko_pages),
                "coingecko_completed_pages": completed_pages,
                "coingecko_rows": len(market_rows),
                "dexscreener_rows": len(dex_rows),
                "combined_rows": len(normalized),
                "cross_source_parallel": True,
                "ethereum_contract_resolutions": resolutions,
            },
            "chain_coverage": {
                "ethereum": "market_discovery_plus_whale_probe_supported",
                "other_chains": "market_discovery_only_whale_probe_not_yet_supported",
            },
            "top_candidates": deduped[: max(1, top_n)],
            "quality_note": (
                "Discovery ranks unusual market acceleration. It is not itself whale confirmation "
                "and does not create orders or paper entries."
            ),
        }

    @staticmethod
    def _from_coingecko(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": row.get("name"),
            "symbol": str(row.get("symbol", "")).upper(),
            "coin_id": row.get("id"),
            "source": "CoinGecko",
            "chain": "multi",
            "token_address": None,
            "price": row.get("price"),
            "change_5m": None,
            "change_1h": row.get("change_1h"),
            "change_6h": None,
            "change_24h": row.get("change_24h"),
            "change_7d": row.get("change_7d"),
            "volume_24h": row.get("volume_24h"),
            "market_cap": row.get("market_cap"),
            "liquidity_usd": None,
            "rank": row.get("rank"),
        }

    @staticmethod
    def _from_dex(row: dict[str, Any]) -> dict[str, Any]:
        return {
            "name": row.get("name"),
            "symbol": str(row.get("symbol", "")).upper(),
            "coin_id": None,
            "source": "DexScreener",
            "chain": str(row.get("chain") or "").lower() or "unknown",
            "token_address": row.get("token_address"),
            "price": row.get("price"),
            "change_5m": row.get("change_5m"),
            "change_1h": row.get("change_1h"),
            "change_6h": row.get("change_6h"),
            "change_24h": row.get("change_24h"),
            "change_7d": row.get("change_7d"),
            "volume_24h": row.get("volume_24h"),
            "market_cap": row.get("market_cap"),
            "liquidity_usd": row.get("liquidity_usd"),
            "rank": row.get("rank"),
            "pair_url": row.get("pair_url"),
        }

    @classmethod
    def _score(cls, row: dict[str, Any]) -> float:
        change_5m = cls._number(row.get("change_5m"))
        change_1h = cls._number(row.get("change_1h"))
        change_6h = cls._number(row.get("change_6h"))
        change_24h = cls._number(row.get("change_24h"))
        volume = cls._number(row.get("volume_24h"))
        market_cap = cls._number(row.get("market_cap"))
        liquidity = cls._number(row.get("liquidity_usd"))
        source_consensus = int(row.get("source_consensus") or 1)

        baseline_1h = change_24h / 24.0
        acceleration_1h = change_1h - baseline_1h
        acceleration_5m = change_5m - (change_1h / 12.0)

        volume_strength = 0.0
        if market_cap > 0:
            volume_strength = min(30.0, (volume / market_cap) * 100.0)
        liquidity_strength = min(10.0, liquidity / 250_000.0) if liquidity > 0 else 0.0

        score = (
            change_5m * 1.2
            + change_1h * 2.0
            + change_6h * 0.8
            + change_24h * 0.25
            + acceleration_5m * 1.5
            + acceleration_1h * 1.4
            + volume_strength
            + liquidity_strength
            + (4.0 if source_consensus >= 2 else 0.0)
        )
        return round(score, 2)

    @classmethod
    def _status(cls, row: dict[str, Any]) -> str:
        score = cls._number(row.get("discovery_score"))
        change_5m = cls._number(row.get("change_5m"))
        change_1h = cls._number(row.get("change_1h"))
        change_24h = cls._number(row.get("change_24h"))

        if score >= 35 and (change_1h >= 8 or change_5m >= 3):
            return "explosive_acceleration"
        if score >= 20 and (change_1h >= 4 or change_24h >= 12):
            return "accelerating"
        if score >= 10:
            return "watch"
        return "background"

    @staticmethod
    def _initial_whale_status(row: dict[str, Any]) -> str:
        chain = str(row.get("chain") or "").lower()
        address = str(row.get("token_address") or "")
        if chain == "ethereum" and address.startswith("0x") and len(address) == 42:
            return "PENDING"
        if chain not in {"", "multi", "unknown", "ethereum"}:
            return "CHAIN_UNSUPPORTED"
        return "NOT_EVALUATED_NO_CONTRACT"

    @staticmethod
    def _initial_whale_reason(row: dict[str, Any]) -> str:
        status = DiscoveryMeshService._initial_whale_status(row)
        if status == "PENDING":
            return "Ethereum contract available; focused whale probe can run."
        if status == "CHAIN_UNSUPPORTED":
            return "Market move detected, but this chain has no whale adapter yet."
        return "Market move detected, but no chain-specific contract is available for whale probing."

    @staticmethod
    def _dedupe(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
        best: dict[str, dict[str, Any]] = {}
        for row in rows:
            address = str(row.get("token_address") or "").lower()
            chain = str(row.get("chain") or "").lower()
            symbol = str(row.get("symbol") or "").upper()
            source = str(row.get("source") or "")
            key = f"{chain}:{address}" if address else f"{source}:{symbol}"
            current = best.get(key)
            if current is None or float(row.get("discovery_score") or 0.0) > float(
                current.get("discovery_score") or 0.0
            ):
                best[key] = row
        return list(best.values())

    @staticmethod
    def _number(value: object) -> float:
        return float(value) if isinstance(value, (int, float)) else 0.0
