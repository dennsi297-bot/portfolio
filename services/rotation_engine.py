from __future__ import annotations

import statistics

from sources.coingecko_source import CoinGeckoSource


STABLE_SYMBOLS = {"USDT", "USDC", "DAI", "USDE", "USDS", "FDUSD", "TUSD", "PYUSD", "FRAX"}
BASE_SYMBOLS = {"BTC", "ETH", "WETH", "WBTC", "STETH", "WSTETH"}


class RotationEngine:
    """Relative strength / capital rotation scanner.

    This module does not change the whale scanner. It answers a different question:
    which coins are outperforming BTC, ETH and the broad altcoin sample?
    """

    def __init__(self, market_source: CoinGeckoSource | None = None) -> None:
        self.market_source = market_source or CoinGeckoSource()

    def scan(self, user_text: str) -> str:
        focus = self._parse_focus(user_text)
        if hasattr(self.market_source, "reset_status"):
            self.market_source.reset_status()

        coins = self._get_rotation_universe(pages=3, per_page=100)
        if not coins:
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
            candidates = [coin for coin in candidates if focus in coin["symbol"].lower() or focus in coin["name"].lower()]

        candidates.sort(key=lambda item: item["score"], reverse=True)
        top = candidates[:10]
        weak = sorted(candidates, key=lambda item: item["score"])[:5]

        return self._format_response(top, weak, btc, eth, alt_proxy_24h, alt_proxy_7d, focus)

    @staticmethod
    def _parse_focus(user_text: str) -> str | None:
        parts = user_text.strip().split(maxsplit=2)
        if len(parts) >= 3 and parts[0].lower() == "scan" and parts[1].lower() == "rotation":
            return parts[2].strip().lower() or None
        return None

    def _get_rotation_universe(self, pages: int = 3, per_page: int = 100) -> list[dict]:
        universe: list[dict] = []
        for page in range(1, pages + 1):
            page_rows = self.market_source.get_market_page(page=page, per_page=per_page)
            universe.extend(page_rows)
        return universe

    @staticmethod
    def _find_symbol(coins: list[dict], symbol: str) -> dict | None:
        for coin in coins:
            if coin.get("symbol") == symbol:
                return coin
        return None

    @staticmethod
    def _safe_number(value: object, fallback: float = 0.0) -> float:
        if isinstance(value, (int, float)):
            return float(value)
        return fallback

    def _alt_proxy(self, coins: list[dict], field: str) -> float:
        values = []
        for coin in coins:
            symbol = str(coin.get("symbol", "")).upper()
            if symbol in STABLE_SYMBOLS or symbol in BASE_SYMBOLS:
                continue
            value = coin.get(field)
            if isinstance(value, (int, float)):
                values.append(float(value))
        if not values:
            return 0.0
        return round(statistics.median(values), 2)

    def _build_candidates(
        self,
        coins: list[dict],
        btc: dict,
        eth: dict,
        alt_proxy_24h: float,
        alt_proxy_7d: float,
    ) -> list[dict]:
        btc_24h = self._safe_number(btc.get("change_24h"))
        eth_24h = self._safe_number(eth.get("change_24h"))
        btc_7d = self._safe_number(btc.get("change_7d"))
        eth_7d = self._safe_number(eth.get("change_7d"))

        candidates = []
        for coin in coins:
            symbol = str(coin.get("symbol", "")).upper()
            if not symbol or symbol in STABLE_SYMBOLS or symbol in BASE_SYMBOLS:
                continue

            change_24h = self._safe_number(coin.get("change_24h"))
            change_7d = self._safe_number(coin.get("change_7d"))
            volume_24h = self._safe_number(coin.get("volume_24h"))
            market_cap = self._safe_number(coin.get("market_cap"))

            rs_btc_24h = round(change_24h - btc_24h, 2)
            rs_eth_24h = round(change_24h - eth_24h, 2)
            rs_alt_24h = round(change_24h - alt_proxy_24h, 2)
            rs_btc_7d = round(change_7d - btc_7d, 2)
            rs_eth_7d = round(change_7d - eth_7d, 2)
            rs_alt_7d = round(change_7d - alt_proxy_7d, 2)

            volume_strength = 0.0
            if market_cap > 0 and volume_24h > 0:
                volume_strength = min(25.0, (volume_24h / market_cap) * 100)

            score = round(
                rs_btc_24h * 1.4
                + rs_eth_24h * 1.2
                + rs_alt_24h * 1.4
                + rs_btc_7d * 0.7
                + rs_eth_7d * 0.6
                + rs_alt_7d * 0.7
                + volume_strength,
                2,
            )
            status = self._classify_status(change_24h, rs_btc_24h, rs_eth_24h, rs_alt_24h, volume_strength)
            signal = self._signal_text(symbol, status)

            candidates.append(
                {
                    "name": coin.get("name") or symbol,
                    "symbol": symbol,
                    "rank": coin.get("rank"),
                    "price": coin.get("price"),
                    "change_24h": change_24h,
                    "change_7d": change_7d,
                    "volume_24h": volume_24h,
                    "market_cap": market_cap,
                    "volume_strength": round(volume_strength, 2),
                    "rs_btc_24h": rs_btc_24h,
                    "rs_eth_24h": rs_eth_24h,
                    "rs_alt_24h": rs_alt_24h,
                    "rs_btc_7d": rs_btc_7d,
                    "rs_eth_7d": rs_eth_7d,
                    "rs_alt_7d": rs_alt_7d,
                    "score": score,
                    "status": status,
                    "signal": signal,
                    "whale_confirmation": "unklar",
                }
            )
        return candidates

    @staticmethod
    def _classify_status(change_24h: float, rs_btc: float, rs_eth: float, rs_alt: float, volume_strength: float) -> str:
        if rs_btc > 5 and rs_eth > 5 and rs_alt > 5 and change_24h > 0 and volume_strength >= 4:
            return "momentum rotation"
        if rs_btc > 3 and rs_eth > 3 and rs_alt > 3:
            return "outperforming"
        if change_24h < 0 and rs_btc > 2 and rs_eth > 2 and rs_alt > 2:
            return "defensive strength"
        if rs_btc > 1.5 and rs_eth > 1.5:
            return "watch only"
        return "weak / underperforming"

    @staticmethod
    def _signal_text(symbol: str, status: str) -> str:
        if status == "momentum rotation":
            return f"Kapital rotiert wahrscheinlich aktiv in {symbol}; Coin schlaegt Markt und Volumen ist auffaellig."
        if status == "outperforming":
            return f"{symbol} outperformt BTC, ETH und Altmarkt. Rotation moeglich."
        if status == "defensive strength":
            return f"{symbol} faellt weniger als der Markt. Kaeufer verteidigen moeglicherweise den Coin."
        if status == "watch only":
            return f"{symbol} zeigt erste relative Staerke, aber noch kein starkes Rotationssignal."
        return f"{symbol} underperformt oder zeigt keine klare Rotation."

    def _source_status_lines(self) -> list[str]:
        statuses = getattr(self.market_source, "source_status", {})
        lines = ["Source Status:"]
        for name in ["CoinGecko", "DexScreener"]:
            if name in statuses:
                lines.append(f"{name}: {statuses[name]}")
        return lines

    @staticmethod
    def _fmt_pct(value: object) -> str:
        if isinstance(value, (int, float)):
            return f"{value:+.2f}%"
        return "n/a"

    @staticmethod
    def _fmt_usd(value: object) -> str:
        if isinstance(value, (int, float)):
            if value >= 1_000_000_000:
                return f"${value / 1_000_000_000:.2f}B"
            if value >= 1_000_000:
                return f"${value / 1_000_000:.2f}M"
            if value >= 1_000:
                return f"${value / 1_000:.2f}K"
            return f"${value:.2f}"
        return "n/a"

    def _market_regime(self, btc_24h: float, eth_24h: float, alt_24h: float) -> str:
        if btc_24h > 1 and eth_24h > 1 and alt_24h > 0:
            return "risk-on"
        if btc_24h < -1 and eth_24h < -1 and alt_24h < 0:
            return "defensiv"
        return "mixed"

    def _format_response(
        self,
        top: list[dict],
        weak: list[dict],
        btc: dict,
        eth: dict,
        alt_proxy_24h: float,
        alt_proxy_7d: float,
        focus: str | None,
    ) -> str:
        btc_24h = self._safe_number(btc.get("change_24h"))
        eth_24h = self._safe_number(eth.get("change_24h"))
        regime = self._market_regime(btc_24h, eth_24h, alt_proxy_24h)

        lines = [
            "Rotation Scan fertig. Relative Strength / Capital Rotation:",
            *self._source_status_lines(),
            "Market Regime:",
            f"BTC 24h: {self._fmt_pct(btc_24h)}",
            f"ETH 24h: {self._fmt_pct(eth_24h)}",
            f"Altmarkt Proxy 24h: {self._fmt_pct(alt_proxy_24h)}",
            f"Altmarkt Proxy 7d: {self._fmt_pct(alt_proxy_7d)}",
            f"Risk-Modus: {regime}",
            "Top Rotation Candidates:",
        ]

        if not top:
            if focus:
                lines.append(f"Kein Rotationstreffer fuer {focus.upper()} in den aktuellen Top-Marktdaten gefunden.")
            else:
                lines.append("Keine starken Rotationstreffer gefunden.")
        else:
            for index, coin in enumerate(top, start=1):
                lines.extend(
                    [
                        f"{index}. {coin['name']} ({coin['symbol']}) | rotation_candidate | score {coin['score']:.2f} | status {coin['status']}",
                        f"   Relative Strength: BTC {self._fmt_pct(coin['rs_btc_24h'])} | ETH {self._fmt_pct(coin['rs_eth_24h'])} | Altmarkt {self._fmt_pct(coin['rs_alt_24h'])}",
                        f"   24h: {self._fmt_pct(coin['change_24h'])} | 7d: {self._fmt_pct(coin['change_7d'])} | Volumen 24h: {self._fmt_usd(coin['volume_24h'])} | Volumenstaerke: {coin['volume_strength']:.2f}%",
                        f"   Signal: {coin['signal']}",
                        f"   Whale Confirmation: {coin['whale_confirmation']}",
                    ]
                )

        lines.append("Weak / Underperforming:")
        for index, coin in enumerate(weak, start=1):
            lines.append(
                f"{index}. {coin['name']} ({coin['symbol']}) | score {coin['score']:.2f} | RS BTC {self._fmt_pct(coin['rs_btc_24h'])} | RS ETH {self._fmt_pct(coin['rs_eth_24h'])} | status {coin['status']}"
            )

        lines.extend(
            [
                "Notes:",
                "Dieser Modus sucht keine Wallets, sondern relative Staerke gegen BTC, ETH und Altmarkt-Proxy.",
                "Kein Watchlist-Bias: ohne Fokus wird breit ueber Top-Marktdaten gescannt.",
                "Volumenstaerke ist aktuell Volume/MarketCap-Proxy, keine echte Volumenveraenderung gegen Vortag.",
                "Whale Confirmation ist hier zunaechst unklar und wird spaeter mit dem Whale-Scan verknuepft.",
            ]
        )
        return "\n".join(lines)
