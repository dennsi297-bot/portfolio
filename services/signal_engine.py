import requests

from config.settings import (
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
)
from models.domain_models import ScanDiagnostics, TokenMetadata, TokenTransferEvent, WhaleSignal
from sources.etherscan_source import EtherscanSource
from utils.decode_utils import decode_uint256
from utils.text_utils import format_time_window, parse_address_from_topic


class WhaleSignalEngine:
    """
    Real signal engine based on ERC-20 transfer activity.
    Placeholder boundaries are kept explicit in response text and TODO comments.
    """

    def __init__(self, source: EtherscanSource) -> None:
        self.source = source

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

            signals: list[WhaleSignal] = []
            for contract in candidate_contracts:
                metadata = self.source.get_token_metadata(contract)
                if metadata is None:
                    continue

                if metadata.symbol.upper() in STABLECOIN_SYMBOLS:
                    metadata.is_stablecoin = True

                signals.extend(self._build_contract_signals(metadata, logs_by_contract.get(contract, [])))

            if not signals:
                return (
                    "Kein starkes Whale-Cluster gefunden. "
                    "Der Scan ist echt breit ueber ERC-20 Transfers, aber das aktuelle Sample zeigt nichts Starkes."
                )

            diagnostics = ScanDiagnostics(
                sampled_logs=len(erc20_logs),
                focus_term=focus_term,
                source_limitations=[
                    "Etherscan liefert hier nur eine Stichprobe, nicht den kompletten Markt.",
                    "accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells.",
                ],
            )
            ranked_signals = self._rank_signals(signals, focus_term)
            return self._format_scan_response(ranked_signals, diagnostics)
        except requests.RequestException:
            return "Fehler: Der breite Token-Scan ueber Etherscan ist fehlgeschlagen."
        except ValueError:
            return "Fehler: Etherscan hat ungueltige Daten fuer den breiten Token-Scan geliefert."

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

        grouped_signals: dict[tuple[str, int], dict] = {}

        for event in parsed_events:
            if event.amount < threshold:
                continue

            bucket_start = event.timestamp - (event.timestamp % SCAN_WINDOW_SECONDS)
            directional_events = [
                ("accumulation", event.to_address),
                ("distribution", event.from_address),
            ]

            for direction, wallet in directional_events:
                signal_key = (direction, bucket_start)
                if signal_key not in grouped_signals:
                    grouped_signals[signal_key] = {
                        "wallet_counts": {},
                        "event_count": 0,
                        "total_size": 0.0,
                        "time_window": format_time_window(event.timestamp, SCAN_WINDOW_SECONDS),
                    }

                grouped_signals[signal_key]["wallet_counts"][wallet] = (
                    grouped_signals[signal_key]["wallet_counts"].get(wallet, 0) + 1
                )
                grouped_signals[signal_key]["event_count"] += 1
                grouped_signals[signal_key]["total_size"] += event.amount

        signals: list[WhaleSignal] = []
        for (direction, _bucket_start), raw_signal in grouped_signals.items():
            wallet_counts = raw_signal["wallet_counts"]
            wallet_addresses = list(wallet_counts.keys())
            wallet_count = len(wallet_addresses)
            if wallet_count < MIN_CLUSTER_WALLETS:
                continue

            repeated_wallets = sum(1 for count in wallet_counts.values() if count > 1)
            wallet_quality_score = self._calculate_wallet_quality_score(wallet_counts)
            token_relevance_score = self._calculate_token_relevance_score(
                wallet_count=wallet_count,
                event_count=raw_signal["event_count"],
                repeated_wallets=repeated_wallets,
                total_size=raw_signal["total_size"],
                is_stablecoin=metadata.is_stablecoin,
            )
            confidence = self._confidence_from_score(token_relevance_score)
            explanation = self._build_signal_reason(
                symbol=metadata.symbol,
                direction=direction,
                wallet_count=wallet_count,
                repeated_wallets=repeated_wallets,
                confidence=confidence,
            )

            signals.append(
                WhaleSignal(
                    token_symbol=metadata.symbol,
                    token_name=metadata.name,
                    token_contract=metadata.contract,
                    direction=direction,
                    wallet_addresses=wallet_addresses,
                    wallet_count=wallet_count,
                    repeated_wallets=repeated_wallets,
                    event_count=raw_signal["event_count"],
                    total_size=raw_signal["total_size"],
                    time_window=raw_signal["time_window"],
                    large_event_threshold=threshold,
                    wallet_quality_score=wallet_quality_score,
                    token_relevance_score=token_relevance_score,
                    confidence=confidence,
                    explanation=explanation,
                    is_stablecoin=metadata.is_stablecoin,
                )
            )

        return signals

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

        amount = raw_amount / (10 ** metadata.decimals)
        return TokenTransferEvent(
            contract=metadata.contract,
            symbol=metadata.symbol,
            name=metadata.name,
            from_address=parse_address_from_topic(str(topics[1])),
            to_address=parse_address_from_topic(str(topics[2])),
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
    def _calculate_token_relevance_score(
        wallet_count: int,
        event_count: int,
        repeated_wallets: int,
        total_size: float,
        is_stablecoin: bool,
    ) -> float:
        stablecoin_penalty = 1.5 if is_stablecoin else 0.0
        size_bonus = min(4.0, total_size / 1_000_000)
        score = (
            wallet_count * 1.6
            + event_count * 0.4
            + repeated_wallets * 0.8
            + size_bonus
            - stablecoin_penalty
        )
        return round(score, 2)

    @staticmethod
    def _confidence_from_score(score: float) -> str:
        if score >= 18:
            return "high"
        if score >= 9:
            return "medium"
        return "low"

    @staticmethod
    def _build_signal_reason(
        symbol: str,
        direction: str,
        wallet_count: int,
        repeated_wallets: int,
        confidence: str,
    ) -> str:
        direction_text = "akkumulieren" if direction == "accumulation" else "verteilen"
        repeated_text = (
            f", {repeated_wallets} davon mehrfach aktiv"
            if repeated_wallets > 0
            else ""
        )
        return (
            f"{wallet_count} grosse Wallets {direction_text} {symbol} im selben Zeitfenster"
            f"{repeated_text}. Vertrauen: {confidence}."
        )

    def _matches_focus(self, signal: WhaleSignal, focus_term: str | None) -> bool:
        if not focus_term:
            return False

        haystacks = [
            signal.token_symbol.lower(),
            signal.token_name.lower(),
            signal.token_contract.lower(),
        ]
        return any(focus_term in haystack for haystack in haystacks)

    def _rank_signals(self, signals: list[WhaleSignal], focus_term: str | None) -> list[WhaleSignal]:
        def sort_key(signal: WhaleSignal) -> tuple:
            focus_bonus = 1 if self._matches_focus(signal, focus_term) else 0
            non_stable_bonus = 0 if signal.is_stablecoin else 1
            return (
                focus_bonus,
                non_stable_bonus,
                signal.token_relevance_score,
                signal.wallet_count,
                signal.event_count,
            )

        return sorted(signals, key=sort_key, reverse=True)

    def _format_scan_response(self, signals: list[WhaleSignal], diagnostics: ScanDiagnostics) -> str:
        lines = [
            "Scan fertig. Starke Whale-Signale aus der aktuellen Ethereum-Transfer-Stichprobe:",
        ]

        for index, signal in enumerate(signals[:MAX_RESULTS], start=1):
            lines.append(
                f"{index}. {signal.token_symbol} | {signal.token_contract} | {signal.direction} | "
                f"{signal.wallet_count} Wallets | {signal.event_count} Events | "
                f"{signal.total_size:.2f} {signal.token_symbol} | {signal.time_window} | "
                f"confidence {signal.confidence} | {signal.explanation}"
            )

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
