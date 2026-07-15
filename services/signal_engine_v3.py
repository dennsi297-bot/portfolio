from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed

from config.settings import (
    COINGECKO_ENRICH_LIMIT,
    MARKET_LOG_PAGES,
    METADATA_RESOLUTION_WORKERS,
    QUALITY_ARCHITECTURE_VERSION,
    SCAN_LOOKBACK_BLOCKS,
    STABLECOIN_SYMBOLS,
)
from models.domain_models import ScanDiagnostics, TokenMetadata, WhaleSignal
from services.signal_engine_v2 import WhaleSignalEngineV2
from utils.http_client import ExternalAPIError


class WhaleSignalEngineV3(WhaleSignalEngineV2):
    """Quality architecture v3 without reducing wallet or market evidence."""

    def __init__(self, source, market_source=None) -> None:
        super().__init__(source, market_source)
        self.metadata_errors: list[str] = []
        self.metadata_coverage: dict[str, int | float] = {}

    def scan(self, user_text: str) -> str:
        normalized_text = user_text.strip().lower()
        if normalized_text == "scan rotation" or normalized_text.startswith("scan rotation "):
            return super().scan(user_text)
        if normalized_text in {"scan gainers", "scan movers", "scan market", "market", "gainers"}:
            return super().scan(user_text)

        if hasattr(self.source, "reset_status"):
            self.source.reset_status()
        if hasattr(self.market_source, "reset_status"):
            self.market_source.reset_status()
        self.metadata_errors = []
        self.metadata_coverage = {}

        if not self.source.has_api_key():
            return self._structured_failure(
                "Scan fehlgeschlagen.",
                "ETHERSCAN_API_KEY fehlt auf dem Server.",
                "scan_failed",
            )

        focus_term, limitation = self._parse_focus_term(user_text)
        if limitation:
            self.last_scan_snapshot = {
                "ok": False,
                "mode": "whale",
                "status": "unsupported",
                "reason": limitation,
                "signals": [],
            }
            return limitation

        try:
            latest_block = self.source.get_latest_block_number()
            if latest_block is None:
                return self._structured_failure(
                    "Scan fehlgeschlagen.",
                    "Letzter Ethereum-Block konnte nicht gelesen werden.",
                    "scan_failed",
                )

            if hasattr(self.source, "resolve_scan_range"):
                from_block, to_block = self.source.resolve_scan_range(
                    latest_block,
                    SCAN_LOOKBACK_BLOCKS,
                )
            else:
                from_block = max(latest_block - SCAN_LOOKBACK_BLOCKS, 0)
                to_block = latest_block

            market_logs = self.source.get_market_transfer_logs(
                from_block,
                to_block,
                pages=MARKET_LOG_PAGES,
            )
            erc20_logs = self._filter_erc20_logs(market_logs)
            if not erc20_logs:
                self._complete_checkpoint(to_block)
                return self._structured_no_signal(
                    "Keine brauchbaren ERC-20 Transfer-Logs fuer den breiten Scan gefunden.",
                    focus_term,
                    sampled_logs=0,
                )

            candidate_contracts = self._select_candidate_contracts(erc20_logs)
            if not candidate_contracts:
                self._complete_checkpoint(to_block)
                return self._structured_no_signal(
                    "Keine auffaelligen Token-Cluster im aktuellen Markt-Sample gefunden.",
                    focus_term,
                    sampled_logs=len(erc20_logs),
                )

            logs_by_contract: dict[str, list[dict]] = {}
            for log in erc20_logs:
                contract = str(log.get("address", "")).lower()
                if contract in candidate_contracts:
                    logs_by_contract.setdefault(contract, []).append(log)

            metadata_by_contract = self._resolve_metadata_batch(candidate_contracts)
            attempted = len(candidate_contracts)
            resolved = len(metadata_by_contract)
            self.metadata_coverage = {
                "attempted": attempted,
                "resolved": resolved,
                "failed": attempted - resolved,
                "coverage_ratio": round(resolved / attempted, 3) if attempted else 1.0,
            }

            raw_signals: list[WhaleSignal] = []
            for contract in candidate_contracts:
                metadata = metadata_by_contract.get(contract)
                if metadata is None:
                    continue
                if metadata.symbol.upper() in STABLECOIN_SYMBOLS:
                    metadata.is_stablecoin = True
                raw_signals.extend(
                    self._build_contract_signals(
                        metadata,
                        logs_by_contract.get(contract, []),
                    )
                )

            if not raw_signals:
                if not self.metadata_errors:
                    self._complete_checkpoint(to_block)
                return self._structured_no_signal(
                    "Kein starkes Whale-Cluster im aktuellen ERC-20 Sample gefunden.",
                    focus_term,
                    sampled_logs=len(erc20_logs),
                    metadata_partial=bool(self.metadata_errors),
                )

            cleaned_signals = self._discard_conflicted_signals(raw_signals)
            if not cleaned_signals:
                if not self.metadata_errors:
                    self._complete_checkpoint(to_block)
                return self._structured_no_signal(
                    "Kein starkes einseitiges Whale-Cluster gefunden. Mixed-flow Tokens wurden verworfen.",
                    focus_term,
                    sampled_logs=len(erc20_logs),
                    metadata_partial=bool(self.metadata_errors),
                )

            transfer_ranked = self._rank_by_transfer_strength(cleaned_signals, focus_term)
            enrich_candidates = transfer_ranked[:COINGECKO_ENRICH_LIMIT]
            enriched_signals = [self._enrich_signal(signal) for signal in enrich_candidates]
            final_ranked = self._rank_signals(enriched_signals, focus_term)

            display_signals = final_ranked
            if focus_term:
                display_signals = [
                    signal
                    for signal in final_ranked
                    if self._matches_focus(signal, focus_term)
                ]

            if self.metadata_errors:
                for signal in display_signals:
                    if "partial_metadata_coverage" not in signal.quality_flags:
                        signal.quality_flags.append("partial_metadata_coverage")

            diagnostics = ScanDiagnostics(
                sampled_logs=len(erc20_logs),
                focus_term=focus_term,
                source_limitations=[
                    "Transfer-Erkennung ist real und basiert auf Ethereum ERC-20 Logs.",
                    "Mehrfachmessung bleibt erhalten; inkrementelle Laeufe nutzen eine Block-Ueberlappung.",
                    "Audit-Refresh scannt weiterhin das volle konfigurierte Rueckblickfenster.",
                    "CoinGecko wird nur fuer Markt-Kontext genutzt, nicht fuer die Wallet-Erkennung.",
                    "Buy/Sell ist noch nicht DEX-bestaetigt; Transfer-Richtung bleibt ein Proxy.",
                ],
            )
            text = self._format_scan_response(display_signals, diagnostics)
            complete = not self.metadata_errors
            if complete:
                self._complete_checkpoint(to_block)
            self.last_scan_snapshot.update(
                {
                    "quality_architecture": QUALITY_ARCHITECTURE_VERSION,
                    "scan_range": self._source_scan_range(),
                    "metadata_coverage": self.metadata_coverage,
                    "metadata_errors": list(self.metadata_errors),
                    "scan_completeness": "complete" if complete else "partial",
                    "decision_eligible": complete,
                }
            )
            return text
        except ExternalAPIError as exc:
            return self._structured_failure(
                "Scan fehlgeschlagen.",
                f"Externe Datenquelle ausgefallen oder zu langsam: {exc.source} ({exc.kind}).",
                "api_failed",
                error=str(exc),
            )
        except ValueError as exc:
            return self._structured_failure(
                "Scan fehlgeschlagen.",
                "Eine Datenquelle hat ungueltige Daten fuer den Scan geliefert.",
                "scan_failed",
                error=str(exc),
            )

    def _resolve_metadata_batch(
        self,
        contracts: list[str],
    ) -> dict[str, TokenMetadata]:
        resolved: dict[str, TokenMetadata] = {}
        workers = max(1, min(METADATA_RESOLUTION_WORKERS, len(contracts)))
        if workers == 1:
            for contract in contracts:
                self._resolve_one_metadata(contract, resolved)
            return resolved

        with ThreadPoolExecutor(max_workers=workers) as executor:
            futures = {
                executor.submit(self.source.get_token_metadata, contract): contract
                for contract in contracts
            }
            for future in as_completed(futures):
                contract = futures[future]
                try:
                    metadata = future.result()
                except ExternalAPIError as exc:
                    self.metadata_errors.append(str(exc))
                    continue
                except (TypeError, ValueError) as exc:
                    self.metadata_errors.append(f"{contract}: {exc}")
                    continue
                if metadata is not None:
                    resolved[contract] = metadata
        return resolved

    def _resolve_one_metadata(
        self,
        contract: str,
        resolved: dict[str, TokenMetadata],
    ) -> None:
        try:
            metadata = self.source.get_token_metadata(contract)
        except ExternalAPIError as exc:
            self.metadata_errors.append(str(exc))
            return
        if metadata is not None:
            resolved[contract] = metadata

    def _structured_no_signal(
        self,
        reason: str,
        focus: str | None,
        *,
        sampled_logs: int,
        metadata_partial: bool = False,
    ) -> str:
        self.last_scan_snapshot = {
            "ok": True,
            "mode": "whale",
            "status": "no_signal",
            "reason": reason,
            "quality_architecture": QUALITY_ARCHITECTURE_VERSION,
            "scan_range": self._source_scan_range(),
            "metadata_coverage": self.metadata_coverage,
            "metadata_errors": list(self.metadata_errors),
            "scan_completeness": "partial" if metadata_partial else "complete",
            "decision_eligible": not metadata_partial,
            "summary": {
                "events_scanned": sampled_logs,
                "clusters": 0,
                "actionable": 0,
                "context": 0,
                "ignored": 0,
                "focus": focus,
            },
            "signals": [],
        }
        return self._format_failure_response(
            "Scan erfolgreich, aber kein Signal.",
            reason,
            "no_signal",
        )

    def _structured_failure(
        self,
        title: str,
        reason: str,
        status: str,
        *,
        error: str | None = None,
    ) -> str:
        self.last_scan_snapshot = {
            "ok": False,
            "mode": "whale",
            "status": status,
            "reason": reason,
            "error": error,
            "quality_architecture": QUALITY_ARCHITECTURE_VERSION,
            "scan_range": self._source_scan_range(),
            "metadata_coverage": self.metadata_coverage,
            "metadata_errors": list(self.metadata_errors),
            "scan_completeness": "failed",
            "decision_eligible": False,
            "signals": [],
        }
        return self._format_failure_response(title, reason, status)

    def _complete_checkpoint(self, to_block: int) -> None:
        if hasattr(self.source, "complete_scan"):
            self.source.complete_scan(to_block)

    def _source_scan_range(self) -> dict:
        return dict(getattr(self.source, "scan_range", {}))
