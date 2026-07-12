from __future__ import annotations

from config.settings import (
    BASE_CONTEXT_SYMBOLS,
    BLACKLIST_SYMBOLS,
    LARGE_EVENT_PERCENTILE,
    MAX_COUNTERPARTY_CONCENTRATION,
    MAX_HUB_COUNTERPARTIES,
    MIN_CLUSTER_WALLETS,
    MIN_CONFIRMED_SCORE,
    MIN_ESTIMATED_NOTIONAL_USD,
    MIN_TOKEN_EVENTS,
    SIGNAL_ENGINE_VERSION,
    STABLECOIN_SYMBOLS,
    WATCHLIST_SYMBOLS,
)
from models.domain_models import ScanDiagnostics, TokenMetadata, WhaleSignal
from services.rotation_engine_v2 import RotationEngineV2
from services.signal_engine import WhaleSignalEngine
from utils.text_utils import format_time_window


class WhaleSignalEngineV2(WhaleSignalEngine):
    """Signal-quality v2 on top of the original real ERC-20 scanner.

    Key changes:
    - raw token units no longer inflate strength across incomparable tokens
    - portfolio/watchlist relevance is separated from discovery quality
    - concentrated hub counterparties are flagged and penalized
    - market-backed USD notional and liquidity influence actionability
    - structured snapshots are exposed for OpenClaw without breaking text clients
    """

    def __init__(self, source, market_source=None) -> None:
        super().__init__(source, market_source)
        self.rotation_engine = RotationEngineV2(self.market_source)
        self.last_scan_snapshot: dict = {}
        self.last_market_snapshot: dict = {}

    def scan_market_movers(self) -> str:
        response = super().scan_market_movers()
        self.last_market_snapshot = {
            "ok": "Keine Market-Mover-Daten erreichbar" not in response,
            "mode": "market",
            "source_status": self._collect_source_status(include_etherscan=False),
            "movers": list(getattr(self.market_source, "last_market_movers", [])),
        }
        return response

    def _build_contract_signals(self, metadata: TokenMetadata, logs: list[dict]) -> list[WhaleSignal]:
        parsed_events = []
        for log in logs:
            event = self._parse_token_event(log, metadata)
            if event is not None:
                parsed_events.append(event)
        if len(parsed_events) < MIN_TOKEN_EVENTS:
            return []

        threshold = self._calculate_large_event_threshold([event.amount for event in parsed_events])
        if threshold is None or threshold <= 0:
            return []

        grouped_windows: dict[int, dict] = {}
        for event in parsed_events:
            if event.amount < threshold:
                continue
            bucket_start = event.timestamp - (event.timestamp % self._scan_window_seconds())
            if bucket_start not in grouped_windows:
                grouped_windows[bucket_start] = {
                    "sender_counts": {},
                    "receiver_counts": {},
                    "event_count": 0,
                    "total_size": 0.0,
                    "time_window": format_time_window(event.timestamp, self._scan_window_seconds()),
                }
            window = grouped_windows[bucket_start]
            window["sender_counts"][event.from_address] = window["sender_counts"].get(event.from_address, 0) + 1
            window["receiver_counts"][event.to_address] = window["receiver_counts"].get(event.to_address, 0) + 1
            window["event_count"] += 1
            window["total_size"] += event.amount

        signals: list[WhaleSignal] = []
        for window_data in grouped_windows.values():
            sender_counts = window_data["sender_counts"]
            receiver_counts = window_data["receiver_counts"]
            accumulation = self._build_direction_signal(
                metadata,
                "accumulation",
                receiver_counts,
                sender_counts,
                window_data,
                threshold,
            )
            distribution = self._build_direction_signal(
                metadata,
                "distribution",
                sender_counts,
                receiver_counts,
                window_data,
                threshold,
            )
            if accumulation and distribution:
                continue
            if accumulation:
                signals.append(accumulation)
            if distribution:
                signals.append(distribution)
        return signals

    @staticmethod
    def _scan_window_seconds() -> int:
        from config.settings import SCAN_WINDOW_SECONDS

        return SCAN_WINDOW_SECONDS

    def _build_direction_signal(
        self,
        metadata: TokenMetadata,
        direction: str,
        primary_counts: dict[str, int],
        counter_counts: dict[str, int],
        raw_window: dict,
        threshold: float,
    ) -> WhaleSignal | None:
        signal = super()._build_direction_signal(
            metadata,
            direction,
            primary_counts,
            counter_counts,
            raw_window,
            threshold,
        )
        if signal is None:
            return None

        event_count = max(int(raw_window.get("event_count", 0)), 1)
        signal.counterparty_count = len(counter_counts)
        signal.counterparty_concentration = (
            max(counter_counts.values()) / event_count if counter_counts else 0.0
        )
        if self._is_hub_concentrated(signal):
            signal.quality_flags.append("centralized_counterparty_pattern")
        return signal

    @staticmethod
    def _calculate_large_event_threshold(amounts: list[float]) -> float | None:
        positive_amounts = sorted(amount for amount in amounts if amount > 0)
        if not positive_amounts:
            return None
        return positive_amounts[int((len(positive_amounts) - 1) * LARGE_EVENT_PERCENTILE)]

    @staticmethod
    def _calculate_transfer_strength_score(
        wallet_count: int,
        event_count: int,
        repeated_wallets: int,
        total_size: float,
        directional_score: float,
        direction: str,
    ) -> float:
        # Raw token quantity is intentionally excluded because token units are incomparable.
        direction_bonus = 4.0 if direction == "accumulation" else 0.0
        return round(
            wallet_count * 2.2
            + event_count * 0.5
            + repeated_wallets * 1.3
            + directional_score * 6.0
            + direction_bonus,
            2,
        )

    def _has_trusted_identity(self, signal: WhaleSignal) -> bool:
        # Portfolio/watchlist relevance is not proof of token identity.
        return bool(signal.market_context and signal.market_context.available)

    def _enrich_signal(self, signal: WhaleSignal) -> WhaleSignal:
        market_context = self.market_source.get_market_context(signal.token_contract)
        signal.market_context = market_context
        if market_context.available:
            if market_context.token_name:
                signal.token_name = market_context.token_name
            if market_context.token_symbol:
                signal.token_symbol = market_context.token_symbol
            if market_context.current_price_usd is not None:
                signal.estimated_notional_usd = max(
                    0.0,
                    signal.total_size * market_context.current_price_usd,
                )

        signal.score_breakdown = self._score_components(signal)
        signal.discovery_score = round(sum(signal.score_breakdown.values()), 2)
        signal.portfolio_bonus = 4.0 if signal.token_symbol.upper() in WATCHLIST_SYMBOLS else 0.0
        signal.token_relevance_score = round(signal.discovery_score + signal.portfolio_bonus, 2)
        signal.quality_tier = self._quality_tier(signal)
        signal.confidence = self._confidence_from_score(signal.discovery_score)
        signal.explanation = self._build_final_reason(signal)
        return signal

    def _score_components(self, signal: WhaleSignal) -> dict[str, float]:
        symbol = signal.token_symbol.upper()
        context = signal.market_context
        components: dict[str, float] = {
            "transfer_cluster": signal.transfer_strength_score,
            "direction": 5.0 if signal.direction == "accumulation" else -2.0,
            "direction_quality": 2.0 if signal.directional_score >= 0.75 else (-2.0 if signal.directional_score < 0.65 else 0.0),
            "wallet_quality": 2.0 if signal.wallet_quality_score >= 1.4 else 0.0,
            "identity": 2.0 if self._has_trusted_identity(signal) else -6.0,
        }

        if self._is_hub_concentrated(signal):
            components["counterparty_pattern"] = -8.0 if signal.direction == "accumulation" else -4.0
        else:
            components["counterparty_pattern"] = 1.0 if signal.counterparty_count >= 3 else 0.0

        if signal.estimated_notional_usd is None:
            components["usd_notional"] = -2.0
        elif signal.estimated_notional_usd >= 250_000:
            components["usd_notional"] = 4.0
        elif signal.estimated_notional_usd >= MIN_ESTIMATED_NOTIONAL_USD:
            components["usd_notional"] = 2.0
        elif signal.estimated_notional_usd >= 25_000:
            components["usd_notional"] = 0.5
        else:
            components["usd_notional"] = -6.0

        if context and context.available:
            if context.market_profile == "mid-cap":
                components["market_profile"] = 1.5
            elif context.market_profile == "obscure":
                components["market_profile"] = 0.5
            else:
                components["market_profile"] = -1.0

            volume = context.volume_24h_usd
            if volume is None:
                components["liquidity"] = -1.0
            elif volume >= 10_000_000:
                components["liquidity"] = 2.0
            elif volume >= 2_000_000:
                components["liquidity"] = 1.0
            elif volume < 500_000:
                components["liquidity"] = -3.0
            else:
                components["liquidity"] = 0.0
        else:
            components["market_profile"] = -1.0
            components["liquidity"] = -1.0

        if signal.is_stablecoin or symbol in STABLECOIN_SYMBOLS:
            components["asset_context"] = -3.0
        elif symbol in BASE_CONTEXT_SYMBOLS:
            components["asset_context"] = -8.0
        elif symbol in BLACKLIST_SYMBOLS:
            components["asset_context"] = -30.0
        else:
            components["asset_context"] = 0.0
        return components

    def _is_hub_concentrated(self, signal: WhaleSignal) -> bool:
        return (
            signal.counterparty_count <= MAX_HUB_COUNTERPARTIES
            and signal.counterparty_concentration >= MAX_COUNTERPARTY_CONCENTRATION
        )

    def _quality_tier(self, signal: WhaleSignal) -> str:
        classification = self._classify_signal(signal)
        if classification == "actionable":
            return "actionable"
        if (
            signal.direction == "accumulation"
            and self._has_trusted_identity(signal)
            and signal.discovery_score >= MIN_CONFIRMED_SCORE
            and not self._is_hub_concentrated(signal)
        ):
            return "confirmed"
        if signal.direction == "accumulation" and self._has_trusted_identity(signal):
            return "interesting"
        return "observed"

    def _classify_signal(self, signal: WhaleSignal) -> str:
        symbol = signal.token_symbol.upper()
        if symbol in BLACKLIST_SYMBOLS:
            return "ignore"
        if signal.is_stablecoin or symbol in STABLECOIN_SYMBOLS or symbol in BASE_CONTEXT_SYMBOLS:
            return "context"
        if signal.direction != "accumulation":
            return "context"
        if signal.wallet_count < MIN_CLUSTER_WALLETS:
            return "ignore"
        if not self._has_trusted_identity(signal):
            return "context"
        if self._is_hub_concentrated(signal):
            return "context"
        if (
            signal.estimated_notional_usd is not None
            and signal.estimated_notional_usd < MIN_ESTIMATED_NOTIONAL_USD
        ):
            return "context"
        if signal.discovery_score < MIN_CONFIRMED_SCORE:
            return "context"
        return "actionable"

    def _build_final_reason(self, signal: WhaleSignal) -> str:
        stronger_parts = [
            f"{signal.wallet_count} grosse Wallets",
            f"{signal.event_count} grosse Events",
            f"Richtungsschaerfe {signal.directional_score:.2f}",
            f"Discovery Score {signal.discovery_score:.2f}",
        ]
        if signal.repeated_wallets > 0:
            stronger_parts.append(f"{signal.repeated_wallets} Wallets mehrfach aktiv")
        if signal.estimated_notional_usd is not None:
            stronger_parts.append(f"geschaetztes Notional ${signal.estimated_notional_usd:,.0f}")

        context_note = self._stablecoin_flow_note(signal) or self._base_asset_flow_note(signal)
        if context_note:
            action_text = context_note
        elif signal.direction == "accumulation":
            action_text = (
                "Transferseitiges Akkumulations-Cluster. Ein echter DEX-Buy ist damit noch nicht bewiesen."
            )
        else:
            action_text = "Verteilungs-/Abfluss-Kontext; kein DEX-bestaetigter Sell."

        weaker_parts = []
        if self._is_hub_concentrated(signal):
            weaker_parts.append("ein dominanter Gegenpart kann Airdrop, Router, Bridge oder Exchange sein")
        if not self._has_trusted_identity(signal):
            weaker_parts.append("Markt-Identitaet nicht bestaetigt")
        if signal.estimated_notional_usd is None:
            weaker_parts.append("USD-Notional nicht berechenbar")
        elif signal.estimated_notional_usd < MIN_ESTIMATED_NOTIONAL_USD:
            weaker_parts.append("USD-Notional unter Actionable-Schwelle")
        weaker_text = f" Schwaecher: {', '.join(weaker_parts)}." if weaker_parts else ""
        return f"Interessant wegen {', '.join(stronger_parts)}. {action_text}{weaker_text}".strip()

    def _format_signal_line(self, index: int, signal: WhaleSignal, classification: str) -> list[str]:
        lines = super()._format_signal_line(index, signal, classification)
        notional = (
            f"${signal.estimated_notional_usd:,.0f}"
            if signal.estimated_notional_usd is not None
            else "n/a"
        )
        breakdown = ", ".join(
            f"{name} {value:+.1f}" for name, value in signal.score_breakdown.items()
        )
        flags = ", ".join(signal.quality_flags) if signal.quality_flags else "none"
        lines.extend(
            [
                f"   Signal Level: {signal.quality_tier} | Discovery Score: {signal.discovery_score:.2f} | Portfolio Bonus: {signal.portfolio_bonus:+.2f} | Final Score: {signal.token_relevance_score:.2f}",
                f"   Estimated Notional: {notional} | Counterparties: {signal.counterparty_count} | Counterparty Concentration: {signal.counterparty_concentration:.2f}",
                f"   Score Breakdown: {breakdown}",
                f"   Quality Flags: {flags}",
            ]
        )
        return lines

    def _format_scan_response(self, signals: list[WhaleSignal], diagnostics: ScanDiagnostics) -> str:
        signal_rows = []
        for signal in signals:
            signal_rows.append(
                {
                    "name": signal.token_name,
                    "symbol": signal.token_symbol.upper(),
                    "contract": signal.token_contract,
                    "direction": signal.direction,
                    "classification": self._classify_signal(signal),
                    "quality_tier": signal.quality_tier,
                    "wallet_count": signal.wallet_count,
                    "repeated_wallets": signal.repeated_wallets,
                    "event_count": signal.event_count,
                    "time_window": signal.time_window,
                    "directional_score": signal.directional_score,
                    "wallet_quality_score": signal.wallet_quality_score,
                    "estimated_notional_usd": signal.estimated_notional_usd,
                    "counterparty_count": signal.counterparty_count,
                    "counterparty_concentration": signal.counterparty_concentration,
                    "discovery_score": signal.discovery_score,
                    "portfolio_bonus": signal.portfolio_bonus,
                    "final_score": signal.token_relevance_score,
                    "score_breakdown": signal.score_breakdown,
                    "quality_flags": signal.quality_flags,
                    "explanation": signal.explanation,
                }
            )

        self.last_scan_snapshot = {
            "ok": True,
            "mode": "whale",
            "engine_version": SIGNAL_ENGINE_VERSION,
            "summary": {
                "events_scanned": diagnostics.sampled_logs,
                "clusters": len(signals),
                "actionable": sum(1 for signal in signals if self._classify_signal(signal) == "actionable"),
                "context": sum(1 for signal in signals if self._classify_signal(signal) == "context"),
                "ignored": sum(1 for signal in signals if self._classify_signal(signal) == "ignore"),
                "focus": diagnostics.focus_term,
            },
            "signals": signal_rows,
        }
        text = super()._format_scan_response(signals, diagnostics)
        return "\n".join(
            [
                text,
                f"Engine Version: {SIGNAL_ENGINE_VERSION}",
                "Scoring: Discovery Score excludes transparent Portfolio Bonus.",
                "Actionable requires trusted market identity, non-hub flow, quality score and sufficient USD notional when price is available.",
            ]
        )

    def _collect_source_status(self, include_etherscan: bool = True) -> dict[str, str]:
        statuses: dict[str, str] = {}
        if include_etherscan and hasattr(self.source, "source_status"):
            statuses.update(self.source.source_status)
        if hasattr(self.market_source, "source_status"):
            statuses.update(self.market_source.source_status)
        return statuses
