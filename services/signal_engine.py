import math

import requests

from config.settings import (
    BASE_CONTEXT_SYMBOLS,
    BLACKLIST_SYMBOLS,
    COINGECKO_ENRICH_LIMIT,
    DEPRIORITIZED_MAJOR_SYMBOLS,
    LARGE_EVENT_PERCENTILE,
    MARKET_LOG_PAGES,
    MAX_METADATA_TOKENS,
    MAX_RESULTS,
    MIN_CLUSTER_WALLETS,
    MIN_TOKEN_EVENTS,
    SCAN_LOOKBACK_BLOCKS,
    SCAN_WINDOW_SECONDS,
    STABLECOIN_SYMBOLS,
    UNSUPPORTED_SCAN_TERMS,
    WATCHLIST_SYMBOLS,
)
from models.domain_models import MarketContext, ScanDiagnostics, TokenMetadata, TokenTransferEvent, WhaleSignal
from sources.coingecko_source import CoinGeckoSource
from sources.etherscan_source import EtherscanSource
from utils.decode_utils import decode_uint256
from utils.text_utils import format_time_window, parse_address_from_topic


class WhaleSignalEngine:
    """
    Signal-first whale scanner.

    Core job:
    - scan broad Ethereum ERC-20 transfer logs
    - find several large wallets accumulating or distributing the same coin in the same time window
    - separate real altcoin opportunities from market context/noise
    """

    def __init__(
        self,
        source: EtherscanSource,
        market_source: CoinGeckoSource | None = None,
    ) -> None:
        self.source = source
        self.market_source = market_source or CoinGeckoSource()

    def scan(self, user_text: str) -> str:
        if not self.source.has_api_key():
            return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

        focus_term, limitation = self._parse_focus_term(user_text)
        if limitation:
            return limitation

        try:
            latest_block = self.source.get_latest_block_number()
            if latest_block is None:
                return "Fehler: Letzter Ethereum-Block konnte nicht gelesen werden."

            from_block = max(latest_block - SCAN_LOOKBACK_BLOCKS, 0)
            market_logs = self.source.get_market_transfer_logs(from_block, latest_block, pages=MARKET_LOG_PAGES)
            erc20_logs = self._filter_erc20_logs(market_logs)
            if not erc20_logs:
                return "Fehler: Keine brauchbaren ERC-20 Transfer-Logs fuer den breiten Scan gefunden."

            candidate_contracts = self._select_candidate_contracts(erc20_logs)
            if not candidate_contracts:
                return "Keine auffaelligen Token-Cluster im aktuellen Markt-Sample gefunden."

            logs_by_contract: dict[str, list[dict]] = {}
            for log in erc20_logs:
                contract = str(log.get("address", "")).lower()
                if contract in candidate_contracts:
                    logs_by_contract.setdefault(contract, []).append(log)

            raw_signals: list[WhaleSignal] = []
            for contract in candidate_contracts:
                metadata = self.source.get_token_metadata(contract)
                if metadata is None:
                    continue

                symbol_upper = metadata.symbol.upper()
                if symbol_upper in STABLECOIN_SYMBOLS:
                    metadata.is_stablecoin = True

                raw_signals.extend(self._build_contract_signals(metadata, logs_by_contract.get(contract, [])))

            if not raw_signals:
                return (
                    "Kein starkes Whale-Cluster gefunden. "
                    "Der Scan ist breit ueber ERC-20 Transfers, aber das aktuelle Sample zeigt nichts Starkes."
                )

            cleaned_signals = self._discard_conflicted_signals(raw_signals)
            if not cleaned_signals:
                return (
                    "Kein starkes einseitiges Whale-Cluster gefunden. "
                    "Tokens mit accumulation und distribution im selben Fenster wurden als mixed_flow verworfen."
                )

            transfer_ranked = self._rank_by_transfer_strength(cleaned_signals, focus_term)
            enrich_candidates = transfer_ranked[:COINGECKO_ENRICH_LIMIT]
            enriched_signals = [self._enrich_signal(signal) for signal in enrich_candidates]
            final_ranked = self._rank_signals(enriched_signals, focus_term)

            diagnostics = ScanDiagnostics(
                sampled_logs=len(erc20_logs),
                focus_term=focus_term,
                source_limitations=[
                    "Transfer-Erkennung ist real und basiert auf Ethereum ERC-20 Logs.",
                    "Gesucht wird: mehrere grosse Wallets bewegen denselben Coin im selben Zeitfenster.",
                    "CoinGecko wird nur fuer Markt-Kontext genutzt, nicht fuer die Erkennung.",
                    "Etherscan liefert hier nur eine Stichprobe, nicht den kompletten Markt.",
                    "accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells.",
                ],
            )
            return self._format_scan_response(final_ranked, diagnostics)
        except requests.RequestException:
            return "Fehler: Der breite Token-Scan oder Markt-Kontext-Scan ist fehlgeschlagen."
        except ValueError:
            return "Fehler: Eine Datenquelle hat ungueltige Daten fuer den Scan geliefert."

    def _parse_focus_term(self, text: str) -> tuple[str | None, str | None]:
        parts = text.split(maxsplit=1)
        if len(parts) == 1:
            return None, None

        focus_term = parts[1].strip().lower()
        if not focus_term:
            return None, None

        limitation = UNSUPPORTED_SCAN_TERMS.get(focus_term)
        if limitation:
            return None, limitation
        if focus_term == "market":
            return None, None
        return focus_term, None

    @staticmethod
    def _filter_erc20_logs(logs: list[dict]) -> list[dict]:
        filtered_logs = []
        for log in logs:
            topics = log.get("topics")
            data_hex = log.get("data")
            if not isinstance(topics, list) or len(topics) != 3:
                continue
            if not isinstance(data_hex, str) or data_hex == "0x":
                continue
            filtered_logs.append(log)
        return filtered_logs

    @staticmethod
    def _select_candidate_contracts(logs: list[dict]) -> list[str]:
        counts: dict[str, int] = {}
        for log in logs:
            contract = str(log.get("address", "")).lower()
            if contract:
                counts[contract] = counts.get(contract, 0) + 1

        ranked_contracts = sorted(counts.items(), key=lambda item: item[1], reverse=True)
        return [contract for contract, count in ranked_contracts if count >= MIN_TOKEN_EVENTS][:MAX_METADATA_TOKENS]

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

            bucket_start = event.timestamp - (event.timestamp % SCAN_WINDOW_SECONDS)
            if bucket_start not in grouped_windows:
                grouped_windows[bucket_start] = {
                    "sender_counts": {},
                    "receiver_counts": {},
                    "event_count": 0,
                    "total_size": 0.0,
                    "time_window": format_time_window(event.timestamp, SCAN_WINDOW_SECONDS),
                }

            grouped_windows[bucket_start]["sender_counts"][event.from_address] = (
                grouped_windows[bucket_start]["sender_counts"].get(event.from_address, 0) + 1
            )
            grouped_windows[bucket_start]["receiver_counts"][event.to_address] = (
                grouped_windows[bucket_start]["receiver_counts"].get(event.to_address, 0) + 1
            )
            grouped_windows[bucket_start]["event_count"] += 1
            grouped_windows[bucket_start]["total_size"] += event.amount

        signals: list[WhaleSignal] = []
        for window_data in grouped_windows.values():
            sender_counts = window_data["sender_counts"]
            receiver_counts = window_data["receiver_counts"]

            accumulation_signal = self._build_direction_signal(
                metadata=metadata,
                direction="accumulation",
                primary_counts=receiver_counts,
                counter_counts=sender_counts,
                raw_window=window_data,
                threshold=threshold,
            )
            distribution_signal = self._build_direction_signal(
                metadata=metadata,
                direction="distribution",
                primary_counts=sender_counts,
                counter_counts=receiver_counts,
                raw_window=window_data,
                threshold=threshold,
            )

            if accumulation_signal and distribution_signal:
                continue
            if accumulation_signal:
                signals.append(accumulation_signal)
            if distribution_signal:
                signals.append(distribution_signal)

        return signals

    def _build_direction_signal(
        self,
        metadata: TokenMetadata,
        direction: str,
        primary_counts: dict[str, int],
        counter_counts: dict[str, int],
        raw_window: dict,
        threshold: float,
    ) -> WhaleSignal | None:
        wallet_addresses = list(primary_counts.keys())
        wallet_count = len(wallet_addresses)
        counter_wallet_count = len(counter_counts)
        repeated_wallets = sum(1 for count in primary_counts.values() if count > 1)
        counter_repeated_wallets = sum(1 for count in counter_counts.values() if count > 1)

        if not self._is_strong_direction(
            primary_wallet_count=wallet_count,
            counter_wallet_count=counter_wallet_count,
            primary_repeated_wallets=repeated_wallets,
            counter_repeated_wallets=counter_repeated_wallets,
        ):
            return None

        directional_score = self._calculate_directional_score(wallet_count, counter_wallet_count)
        wallet_quality_score = self._calculate_wallet_quality_score(primary_counts)
        transfer_strength_score = self._calculate_transfer_strength_score(
            wallet_count=wallet_count,
            event_count=raw_window["event_count"],
            repeated_wallets=repeated_wallets,
            total_size=raw_window["total_size"],
            directional_score=directional_score,
            direction=direction,
        )
        explanation = self._build_transfer_reason(
            symbol=metadata.symbol,
            direction=direction,
            wallet_count=wallet_count,
            repeated_wallets=repeated_wallets,
            directional_score=directional_score,
        )

        return WhaleSignal(
            token_symbol=metadata.symbol,
            token_name=metadata.name,
            token_contract=metadata.contract,
            direction=direction,
            wallet_addresses=wallet_addresses,
            wallet_count=wallet_count,
            repeated_wallets=repeated_wallets,
            event_count=raw_window["event_count"],
            total_size=raw_window["total_size"],
            time_window=raw_window["time_window"],
            large_event_threshold=threshold,
            wallet_quality_score=wallet_quality_score,
            token_relevance_score=transfer_strength_score,
            directional_score=directional_score,
            transfer_strength_score=transfer_strength_score,
            confidence=self._confidence_from_score(transfer_strength_score),
            explanation=explanation,
            is_stablecoin=metadata.is_stablecoin,
        )

    @staticmethod
    def _parse_token_event(log: dict, metadata: TokenMetadata) -> TokenTransferEvent | None:
        topics = log.get("topics")
        data_hex = log.get("data")
        timestamp_hex = str(log.get("timeStamp", "0"))
        if not isinstance(topics, list) or len(topics) != 3 or not isinstance(data_hex, str):
            return None

        raw_amount = decode_uint256(data_hex)
        if raw_amount is None:
            return None

        try:
            timestamp = int(timestamp_hex, 16)
        except ValueError:
            return None

        from_address = parse_address_from_topic(str(topics[1]))
        to_address = parse_address_from_topic(str(topics[2]))
        zero_address = "0x0000000000000000000000000000000000000000"
        if from_address == to_address:
            return None
        if from_address == zero_address or to_address == zero_address:
            return None
        if from_address == metadata.contract or to_address == metadata.contract:
            return None

        amount = raw_amount / (10 ** metadata.decimals)
        return TokenTransferEvent(
            contract=metadata.contract,
            symbol=metadata.symbol,
            name=metadata.name,
            from_address=from_address,
            to_address=to_address,
            amount=amount,
            timestamp=timestamp,
        )

    @staticmethod
    def _calculate_large_event_threshold(amounts: list[float]) -> float | None:
        positive_amounts = sorted(amount for amount in amounts if amount > 0)
        if not positive_amounts:
            return None

        threshold_index = int((len(positive_amounts) - 1) * LARGE_EVENT_PERCENTILE)
        return positive_amounts[threshold_index]

    @staticmethod
    def _calculate_wallet_quality_score(wallet_counts: dict[str, int]) -> float:
        if not wallet_counts:
            return 0.0

        weighted_counts = [min(3.0, count) for count in wallet_counts.values()]
        return round(sum(weighted_counts) / len(weighted_counts), 2)

    @staticmethod
    def _calculate_directional_score(wallet_count: int, opposite_wallet_count: int) -> float:
        total = wallet_count + opposite_wallet_count
        if total <= 0:
            return 0.0
        return round(wallet_count / total, 2)

    @staticmethod
    def _calculate_transfer_strength_score(
        wallet_count: int,
        event_count: int,
        repeated_wallets: int,
        total_size: float,
        directional_score: float,
        direction: str,
    ) -> float:
        size_component = min(5.0, math.log10(max(total_size, 1.0)))
        direction_bonus = 5.0 if direction == "accumulation" else 0.0
        score = (
            wallet_count * 2.2
            + event_count * 0.5
            + repeated_wallets * 1.3
            + directional_score * 6.0
            + size_component
            + direction_bonus
        )
        return round(score, 2)

    @staticmethod
    def _confidence_from_score(score: float) -> str:
        if score >= 22:
            return "high"
        if score >= 12:
            return "medium"
        return "low"

    @staticmethod
    def _build_transfer_reason(
        symbol: str,
        direction: str,
        wallet_count: int,
        repeated_wallets: int,
        directional_score: float,
    ) -> str:
        direction_text = "akkumulieren" if direction == "accumulation" else "verteilen"
        stronger_text = "sehr einseitig" if directional_score >= 0.8 else "einseitig"
        weaker_text = (
            " Etwas schwaecher, weil Gegenrichtung im selben Fenster auch sichtbar war."
            if directional_score < 0.75
            else ""
        )
        repeat_text = (
            f" {repeated_wallets} Wallets waren mehrfach aktiv."
            if repeated_wallets > 0
            else ""
        )
        return (
            f"{wallet_count} grosse Wallets {direction_text} {symbol} {stronger_text}."
            f"{repeat_text}{weaker_text}"
        ).strip()

    @staticmethod
    def _discard_conflicted_signals(signals: list[WhaleSignal]) -> list[WhaleSignal]:
        grouped: dict[tuple[str, str], list[WhaleSignal]] = {}
        for signal in signals:
            key = (signal.token_contract, signal.time_window)
            grouped.setdefault(key, []).append(signal)

        cleaned_signals: list[WhaleSignal] = []
        for grouped_signals in grouped.values():
            directions = {signal.direction for signal in grouped_signals}
            if "accumulation" in directions and "distribution" in directions:
                continue
            cleaned_signals.extend(grouped_signals)
        return cleaned_signals

    @staticmethod
    def _is_strong_direction(
        primary_wallet_count: int,
        counter_wallet_count: int,
        primary_repeated_wallets: int,
        counter_repeated_wallets: int,
    ) -> bool:
        if primary_wallet_count < MIN_CLUSTER_WALLETS:
            return False
        if counter_wallet_count == 0:
            return True
        if primary_wallet_count >= counter_wallet_count * 1.5:
            return True
        if primary_wallet_count > counter_wallet_count and primary_repeated_wallets > counter_repeated_wallets:
            return True
        if counter_wallet_count <= 2 and primary_wallet_count >= MIN_CLUSTER_WALLETS:
            return True
        return False

    def _matches_focus(self, signal: WhaleSignal, focus_term: str | None) -> bool:
        if not focus_term:
            return False

        haystacks = [
            signal.token_symbol.lower(),
            signal.token_name.lower(),
            signal.token_contract.lower(),
        ]
        return any(focus_term in haystack for haystack in haystacks)

    def _rank_by_transfer_strength(self, signals: list[WhaleSignal], focus_term: str | None) -> list[WhaleSignal]:
        def sort_key(signal: WhaleSignal) -> tuple:
            focus_bonus = 1 if self._matches_focus(signal, focus_term) else 0
            accumulation_bonus = 1 if signal.direction == "accumulation" else 0
            return (
                focus_bonus,
                accumulation_bonus,
                signal.transfer_strength_score,
                signal.wallet_count,
                signal.repeated_wallets,
            )

        return sorted(signals, key=sort_key, reverse=True)

    def _enrich_signal(self, signal: WhaleSignal) -> WhaleSignal:
        market_context = self.market_source.get_market_context(signal.token_contract)
        signal.market_context = market_context

        if market_context.available:
            if market_context.token_name:
                signal.token_name = market_context.token_name
            if market_context.token_symbol:
                signal.token_symbol = market_context.token_symbol

        signal.token_relevance_score = self._calculate_final_relevance_score(signal)
        signal.confidence = self._confidence_from_score(signal.token_relevance_score)
        signal.explanation = self._build_final_reason(signal)
        return signal

    def _calculate_final_relevance_score(self, signal: WhaleSignal) -> float:
        score = signal.transfer_strength_score
        symbol = signal.token_symbol.upper()
        market_context = signal.market_context

        if signal.direction == "accumulation":
            score += 6.0
        else:
            score -= 2.0

        if symbol in WATCHLIST_SYMBOLS:
            score += 4.0
        if signal.is_stablecoin or symbol in STABLECOIN_SYMBOLS:
            score -= 15.0
        if symbol in BASE_CONTEXT_SYMBOLS:
            score -= 14.0
        if symbol in BLACKLIST_SYMBOLS:
            score -= 30.0

        if market_context and market_context.available:
            if market_context.market_profile == "obscure":
                score += 2.0
            elif market_context.market_profile == "mid-cap":
                score += 1.5
            else:
                score -= 1.0

            if market_context.price_change_24h is not None and abs(market_context.price_change_24h) >= 8:
                score += 1.0
            if market_context.volume_24h_usd is not None and market_context.volume_24h_usd >= 5_000_000:
                score += 0.8
        else:
            score -= 1.0

        return round(score, 2)

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
        return "actionable"

    def _rank_signals(self, signals: list[WhaleSignal], focus_term: str | None) -> list[WhaleSignal]:
        def sort_key(signal: WhaleSignal) -> tuple:
            focus_bonus = 1 if self._matches_focus(signal, focus_term) else 0
            classification = self._classify_signal(signal)
            class_score = {"actionable": 3, "context": 2, "ignore": 1}.get(classification, 0)
            accumulation_bonus = 1 if signal.direction == "accumulation" else 0
            return (
                focus_bonus,
                class_score,
                accumulation_bonus,
                signal.token_relevance_score,
                signal.wallet_count,
                signal.event_count,
            )

        return sorted(signals, key=sort_key, reverse=True)

    def _build_final_reason(self, signal: WhaleSignal) -> str:
        stronger_parts = [
            f"{signal.wallet_count} grosse Wallets",
            f"{signal.event_count} grosse Events",
            f"Richtungsschaerfe {signal.directional_score:.2f}",
        ]
        if signal.repeated_wallets > 0:
            stronger_parts.append(f"{signal.repeated_wallets} Wallets mehrfach aktiv")

        weaker_parts = []
        symbol = signal.token_symbol.upper()
        if signal.is_stablecoin or symbol in STABLECOIN_SYMBOLS:
            weaker_parts.append("Stablecoin = Market Context, kein Altcoin-Trigger")
        if symbol in BASE_CONTEXT_SYMBOLS:
            weaker_parts.append("Base-/Wrapped-Asset = Market Context")
        if symbol in BLACKLIST_SYMBOLS:
            weaker_parts.append("Token steht auf Blacklist")
        if signal.market_context and not signal.market_context.available:
            weaker_parts.append("Markt-Kontext aktuell nicht verfuegbar")

        weaker_text = f" Schwaecher: {', '.join(weaker_parts)}." if weaker_parts else ""
        action_text = (
            "Das ist ein Akkumulations-Cluster: mehrere grosse Wallets sammeln denselben Coin gleichzeitig."
            if signal.direction == "accumulation"
            else "Das ist Verteilungs-/Abfluss-Kontext, kein Kauf-Trigger."
        )
        return (
            f"Interessant wegen {', '.join(stronger_parts)}. "
            f"{action_text}"
            f"{weaker_text}"
        ).strip()

    @staticmethod
    def _format_market_note(market_context: MarketContext | None) -> str:
        if market_context is None:
            return "Markt-Kontext: nicht geladen."
        if not market_context.available:
            limitation = market_context.limitation or "CoinGecko Mapping fehlt."
            return f"Markt-Kontext: nicht verfuegbar ({limitation})"

        categories = ", ".join(market_context.categories[:2]) if market_context.categories else "keine Kategorie"
        price_text = (
            f"${market_context.current_price_usd:.6f}"
            if market_context.current_price_usd is not None
            else "Preis n/a"
        )
        volume_text = (
            f"${market_context.volume_24h_usd:,.0f}"
            if market_context.volume_24h_usd is not None
            else "Volumen n/a"
        )
        change_text = (
            f"{market_context.price_change_24h:.2f}%"
            if market_context.price_change_24h is not None
            else "24h n/a"
        )
        rank_text = (
            str(market_context.market_cap_rank)
            if market_context.market_cap_rank is not None
            else "n/a"
        )
        return (
            f"Markt-Kontext: rank {rank_text}, price {price_text}, vol24h {volume_text}, "
            f"change24h {change_text}, profile {market_context.market_profile}, narrative {categories}."
        )

    def _format_signal_line(self, index: int, signal: WhaleSignal, classification: str) -> list[str]:
        name = signal.token_name or signal.token_symbol
        symbol = signal.token_symbol.upper()
        identity = "high" if signal.market_context and signal.market_context.available else "medium"
        market_note = self._format_market_note(signal.market_context)
        return [
            f"{index}. {name} ({symbol}) | {signal.token_contract} | {signal.direction} | "
            f"{signal.wallet_count} Wallets | {signal.event_count} Events | "
            f"{signal.total_size:.2f} {symbol} | {signal.time_window} | confidence {signal.confidence}",
            f"   Classification: {classification} | Evidence: transfer-based | Identity: {identity}",
            f"   Transfer-Erkennung: real | {signal.explanation}",
            f"   Markt-Enrichment: {'real' if signal.market_context and signal.market_context.available else 'unavailable'} | {market_note}",
        ]

    def _format_scan_response(self, signals: list[WhaleSignal], diagnostics: ScanDiagnostics) -> str:
        actionable = [signal for signal in signals if self._classify_signal(signal) == "actionable"]
        context = [signal for signal in signals if self._classify_signal(signal) == "context"]
        ignored = [signal for signal in signals if self._classify_signal(signal) == "ignore"]

        lines = [
            "Scan fertig. Mehrere grosse Wallets gleichzeitig erkannt:",
            "Top Altcoin Opportunities:",
        ]

        if actionable:
            for index, signal in enumerate(actionable[:MAX_RESULTS], start=1):
                lines.extend(self._format_signal_line(index, signal, "actionable"))
        else:
            lines.append("Keine starken Altcoin-Akkumulationscluster im aktuellen Scan-Fenster gefunden.")

        lines.append("Market Context:")
        if context:
            for index, signal in enumerate(context[:MAX_RESULTS], start=1):
                lines.extend(self._format_signal_line(index, signal, "context_only"))
        else:
            lines.append("Kein relevanter Market Context im aktuellen Scan-Fenster gefunden.")

        lines.append("Filtered / Ignored:")
        if ignored:
            for index, signal in enumerate(ignored[:MAX_RESULTS], start=1):
                lines.extend(self._format_signal_line(index, signal, "ignore"))
        else:
            lines.append("Keine ignorierten Signale im aktuellen Scan-Fenster.")

        if diagnostics.focus_term:
            if any(self._matches_focus(signal, diagnostics.focus_term) for signal in signals):
                lines.append(f"Priorisiert auf: {diagnostics.focus_term.upper()}")
            else:
                lines.append(
                    f"Kein direktes Signal fuer {diagnostics.focus_term.upper()} im aktuellen Sample gefunden."
                )
        else:
            lines.append("Signal-first Modus: Tokens werden erst aus den Events entdeckt, nicht vorgegeben.")

        for limitation in diagnostics.source_limitations:
            lines.append(f"Limit: {limitation}")

        lines.append(f"Real: ERC-20 Transfer-Logs aus {diagnostics.sampled_logs} Events auf Ethereum.")
        return "\n".join(lines)

    # TODO: Add DEX buy/sell detection so transfers can be upgraded to real trade direction.
    # TODO: Add smarter wallet scoring with tagged smart-money and exchange wallet lists.
    # TODO: Add multi-chain providers for Solana, Base, Polygon and Sui.
    # TODO: Add alerting and Telegram integration for strong signals.
