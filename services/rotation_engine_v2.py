from __future__ import annotations

from services.rotation_engine import RotationEngine


class RotationEngineV2(RotationEngine):
    """Rotation engine with a structured snapshot for OpenClaw consumers."""

    def __init__(self, market_source=None) -> None:
        super().__init__(market_source)
        self.last_snapshot: dict = {}

    def scan(self, user_text: str) -> str:
        focus = self._parse_focus(user_text)
        if hasattr(self.market_source, "reset_status"):
            self.market_source.reset_status()

        coins = self._get_rotation_universe(pages=3, per_page=100)
        if not coins:
            self.last_snapshot = {
                "ok": False,
                "mode": "rotation",
                "focus": focus,
                "reason": "no_market_data",
                "decision_eligible": False,
                "freshness_eligible": False,
            }
            return "\n".join(
                [
                    "Rotation Scan fehlgeschlagen.",
                    "Keine Marktdaten fuer Relative-Strength-Scan erhalten.",
                    *self._source_status_lines(),
                    "Status: rotation_failed",
                ]
            )

        btc = self._find_symbol(coins, "BTC")
        eth = self._find_symbol(coins, "ETH")
        if btc is None or eth is None:
            self.last_snapshot = {
                "ok": False,
                "mode": "rotation",
                "focus": focus,
                "reason": "benchmark_missing",
                "decision_eligible": False,
                "freshness_eligible": False,
            }
            return "\n".join(
                [
                    "Rotation Scan fehlgeschlagen.",
                    "BTC oder ETH Benchmark fehlt in den Marktdaten.",
                    *self._source_status_lines(),
                    "Status: rotation_failed",
                ]
            )

        alt_proxy_24h = self._alt_proxy(coins, "change_24h")
        alt_proxy_7d = self._alt_proxy(coins, "change_7d")
        candidates = self._build_candidates(coins, btc, eth, alt_proxy_24h, alt_proxy_7d)

        if focus:
            candidates = [
                coin
                for coin in candidates
                if focus in coin["symbol"].lower() or focus in coin["name"].lower()
            ]

        candidates.sort(key=lambda item: item["score"], reverse=True)
        top = candidates[:10]
        weak = sorted(candidates, key=lambda item: item["score"])[:5]
        btc_24h = self._safe_number(btc.get("change_24h"))
        eth_24h = self._safe_number(eth.get("change_24h"))
        stale = self._market_is_stale()

        for candidate in top:
            candidate["freshness_eligible"] = not stale
            candidate["decision_eligible"] = not stale

        self.last_snapshot = {
            "ok": True,
            "mode": "rotation",
            "focus": focus,
            "freshness": "stale_or_circuit" if stale else "fresh_or_live",
            "freshness_eligible": not stale,
            "decision_eligible": not stale,
            "universe_size": len(coins),
            "market_regime": {
                "btc_24h": btc_24h,
                "eth_24h": eth_24h,
                "alt_proxy_24h": alt_proxy_24h,
                "alt_proxy_7d": alt_proxy_7d,
                "risk_mode": self._market_regime(btc_24h, eth_24h, alt_proxy_24h),
            },
            "top_candidates": top,
            "weak_candidates": weak,
        }
        response = self._format_response(
            top,
            weak,
            btc,
            eth,
            alt_proxy_24h,
            alt_proxy_7d,
            focus,
        )
        if stale:
            response = "\n".join(
                [
                    response,
                    "QUALITY GUARD: Rotation basiert auf stale/degraded Marktdaten.",
                    "Keine neue Trendbestaetigung und keine strong_confluence erlaubt.",
                ]
            )
        return response

    def _market_is_stale(self) -> bool:
        statuses = getattr(self.market_source, "source_status", {})
        return any(
            str(status).startswith("stale_cache_")
            or str(status).startswith("circuit_open_")
            for status in statuses.values()
        )
