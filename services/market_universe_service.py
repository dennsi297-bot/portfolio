from __future__ import annotations

from typing import Any

from config.settings import MARKET_UNIVERSE_MAX_PAGES_PER_REQUEST
from services.evidence_ledger import EvidenceLedger, get_evidence_ledger
from sources.fresh_coingecko_source import FreshCoinGeckoSource


class MarketUniverseService:
    """Rolling broad-market sensor with persistent page coverage."""

    CURSOR_KEY = "market_universe:last_page"

    def __init__(
        self,
        market_source: FreshCoinGeckoSource,
        *,
        run_id: str,
        ledger: EvidenceLedger | None = None,
    ) -> None:
        self.market_source = market_source
        self.run_id = run_id
        self.ledger = ledger or get_evidence_ledger()

    def scan(self, pages_per_run: int, max_pages: int) -> dict[str, Any]:
        max_pages = max(1, min(max_pages, MARKET_UNIVERSE_MAX_PAGES_PER_REQUEST))
        pages_per_run = max(1, min(pages_per_run, max_pages))
        previous = self.ledger.get_int_checkpoint(self.CURSOR_KEY) or 0
        start_page = 1 if previous >= max_pages else previous + 1

        requested_pages = []
        page = start_page
        for _ in range(pages_per_run):
            requested_pages.append(page)
            page += 1
            if page > max_pages:
                page = 1

        benchmark_rows = self.market_source.get_market_page(page=1, per_page=100)
        btc = self._find_symbol(benchmark_rows, "BTC")
        eth = self._find_symbol(benchmark_rows, "ETH")
        rows_by_page: dict[int, list[dict]] = {1: benchmark_rows} if benchmark_rows else {}
        rows: list[dict] = []
        completed_pages: list[int] = []

        for requested_page in requested_pages:
            page_rows = rows_by_page.get(requested_page)
            if page_rows is None:
                page_rows = self.market_source.get_market_page(
                    page=requested_page,
                    per_page=100,
                )
                if page_rows:
                    rows_by_page[requested_page] = page_rows
            if not page_rows:
                break
            rows.extend(page_rows)
            completed_pages.append(requested_page)

        if not completed_pages:
            return {
                "ok": False,
                "mode": "universe",
                "reason": "no_market_data",
                "decision_eligible": False,
                "coverage": {
                    "start_page": start_page,
                    "end_page": start_page,
                    "max_pages": max_pages,
                    "pages_completed": 0,
                    "coins_scanned": 0,
                    "rolling_full_market": True,
                },
                "top_candidates": [],
            }

        last_page = completed_pages[-1]
        complete = len(completed_pages) == len(requested_pages)
        if complete:
            self.ledger.set_checkpoint(self.CURSOR_KEY, last_page)

        candidates = [
            self._candidate(row, btc, eth)
            for row in rows
            if str(row.get("symbol", "")).upper() not in {"BTC", "ETH"}
        ]
        candidates.sort(key=lambda row: row["score"], reverse=True)
        weak = sorted(candidates, key=lambda row: row["score"])[:10]
        result = {
            "ok": complete,
            "mode": "universe",
            "decision_eligible": complete,
            "coverage": {
                "start_page": start_page,
                "end_page": last_page,
                "requested_pages": requested_pages,
                "completed_pages": completed_pages,
                "max_pages": max_pages,
                "pages_completed": len(completed_pages),
                "coins_scanned": len(rows),
                "rolling_full_market": True,
                "wrapped": any(
                    completed_pages[index] < completed_pages[index - 1]
                    for index in range(1, len(completed_pages))
                ),
            },
            "benchmarks": {
                "btc_24h": self._number((btc or {}).get("change_24h")),
                "eth_24h": self._number((eth or {}).get("change_24h")),
            },
            "top_candidates": candidates[:20],
            "weak_candidates": weak,
            "quality_note": (
                "Rolling coverage preserves market breadth across cycles. "
                "A segment result is not represented as a complete-market instant snapshot."
            ),
        }
        self.ledger.record_market_universe(
            self.run_id,
            start_page,
            last_page,
            max_pages,
            result,
        )
        return result

    def _candidate(
        self,
        row: dict,
        btc: dict | None,
        eth: dict | None,
    ) -> dict:
        change_24h = self._number(row.get("change_24h"))
        change_7d = self._number(row.get("change_7d"))
        volume = self._number(row.get("volume_24h"))
        market_cap = self._number(row.get("market_cap"))
        btc_24h = self._number((btc or {}).get("change_24h"))
        eth_24h = self._number((eth or {}).get("change_24h"))
        volume_strength = min(25.0, (volume / market_cap) * 100) if market_cap > 0 else 0.0
        score = round(
            (change_24h - btc_24h) * 1.4
            + (change_24h - eth_24h) * 1.2
            + change_7d * 0.5
            + volume_strength,
            2,
        )
        return {
            **row,
            "score": score,
            "rs_btc_24h": round(change_24h - btc_24h, 2),
            "rs_eth_24h": round(change_24h - eth_24h, 2),
            "volume_strength": round(volume_strength, 2),
            "status": self._status(score, change_24h, volume_strength),
        }

    @staticmethod
    def _find_symbol(rows: list[dict], symbol: str) -> dict | None:
        return next(
            (row for row in rows if str(row.get("symbol", "")).upper() == symbol),
            None,
        )

    @staticmethod
    def _number(value: object) -> float:
        return float(value) if isinstance(value, (int, float)) else 0.0

    @staticmethod
    def _status(score: float, change_24h: float, volume_strength: float) -> str:
        if score >= 15 and change_24h > 0 and volume_strength >= 3:
            return "strong_rotation_candidate"
        if score >= 8:
            return "outperforming"
        if score >= 3:
            return "watch"
        return "weak"
