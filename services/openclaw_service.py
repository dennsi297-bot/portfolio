from __future__ import annotations

import copy
import uuid
from datetime import datetime, timezone

from config.settings import (
    CACHE_POLICIES,
    DEFAULT_CACHE_POLICY,
    OPENCLAW_SCHEMA_VERSION,
    QUALITY_ARCHITECTURE_VERSION,
    SIGNAL_ENGINE_VERSION,
)
from services.evidence_ledger import EvidenceLedger, get_evidence_ledger
from services.market_universe_service import MarketUniverseService
from services.message_service import MessageService
from services.signal_engine_v3 import WhaleSignalEngineV3
from services.wallet_service import WalletService
from sources.fresh_coingecko_source import FreshCoinGeckoSource
from sources.persistent_etherscan_source import PersistentEtherscanSource
from utils.text_utils import is_ethereum_wallet


class OpenClawService:
    """Stable machine-facing adapter for OpenClaw and future agents."""

    ALLOWED_MODES = {
        "whale",
        "market",
        "rotation",
        "confluence",
        "wallet",
        "universe",
    }

    def __init__(self, ledger: EvidenceLedger | None = None) -> None:
        self.ledger = ledger or get_evidence_ledger()

    @staticmethod
    def capabilities() -> dict:
        return {
            "schema_version": OPENCLAW_SCHEMA_VERSION,
            "engine_version": SIGNAL_ENGINE_VERSION,
            "quality_architecture": QUALITY_ARCHITECTURE_VERSION,
            "modes": {
                "whale": "Real Ethereum ERC-20 transfer-cluster scan.",
                "market": "Price/volume movers from CoinGecko with DexScreener fallback.",
                "rotation": "Relative strength versus BTC, ETH and broad alt-market proxy.",
                "confluence": "Independent focused whale plus focused rotation scan.",
                "wallet": "Structured Ethereum wallet balance and recent transactions.",
                "universe": "Rolling broad-market coverage with persistent page cursor.",
            },
            "cache_policies": sorted(CACHE_POLICIES),
            "verification_passes": {"minimum": 1, "maximum": 3},
            "quality_invariants": [
                "Stale market data cannot create actionable signals.",
                "Stale/degraded rotation cannot create strong_confluence.",
                "Multiple verification passes remain independent via audit_refresh.",
                "Incremental wallet scans retain overlap and periodic full-audit support.",
            ],
            "commands": [
                "scan",
                "scan <symbol-or-contract>",
                "scan gainers",
                "scan rotation",
                "scan rotation <symbol>",
                "0x<wallet>",
            ],
            "limitations": [
                "Whale direction is transfer-based and not yet a DEX-confirmed buy/sell.",
                "Ethereum logs remain bounded by Etherscan result limits.",
                "Rolling universe coverage is broad over time, not one instant all-token snapshot.",
                "Portfolio bonus is separate and cannot establish actionability.",
            ],
        }

    def execute(
        self,
        mode: str,
        focus: str | None = None,
        wallet: str | None = None,
        *,
        cache_policy: str = DEFAULT_CACHE_POLICY,
        verification_passes: int = 1,
        run_id: str | None = None,
        market_pages_per_run: int = 3,
        market_max_pages: int = 25,
    ) -> dict:
        normalized_mode = mode.strip().lower()
        normalized_focus = focus.strip().lower() if focus and focus.strip() else None
        self._validate_request(normalized_mode, cache_policy, verification_passes)
        base_run_id = run_id or f"whalebot-{uuid.uuid4().hex[:16]}"

        if verification_passes == 1:
            return self._execute_once(
                normalized_mode,
                normalized_focus,
                wallet,
                cache_policy=cache_policy,
                run_id=base_run_id,
                verification_passes=1,
                market_pages_per_run=market_pages_per_run,
                market_max_pages=market_max_pages,
            )

        self.ledger.start_run(
            base_run_id,
            normalized_mode,
            normalized_focus,
            cache_policy,
            verification_passes,
        )
        try:
            results = []
            for pass_index in range(verification_passes):
                pass_policy = cache_policy if pass_index == 0 else "audit_refresh"
                pass_run_id = f"{base_run_id}-p{pass_index + 1}"
                results.append(
                    self._execute_once(
                        normalized_mode,
                        normalized_focus,
                        wallet,
                        cache_policy=pass_policy,
                        run_id=pass_run_id,
                        verification_passes=verification_passes,
                        market_pages_per_run=market_pages_per_run,
                        market_max_pages=market_max_pages,
                    )
                )

            primary = copy.deepcopy(results[-1])
            verification = self._verification_summary(normalized_mode, results)
            primary["run_id"] = base_run_id
            primary["child_run_ids"] = [result.get("run_id") for result in results]
            primary["verification"] = verification
            primary["verification_passes"] = verification_passes
            primary["decision_eligible"] = bool(
                primary.get("decision_eligible")
                and verification["status"] == "confirmed"
            )
            primary["verification_results"] = results
            status = (
                "COMPLETED"
                if primary.get("ok")
                else "COMPLETED_WITH_SOURCE_ERROR"
            )
            self.ledger.finish_run(base_run_id, status, result=primary)
            return primary
        except Exception as exc:
            self.ledger.finish_run(base_run_id, "FAILED", error=str(exc))
            raise

    def _execute_once(
        self,
        mode: str,
        focus: str | None,
        wallet: str | None,
        *,
        cache_policy: str,
        run_id: str,
        verification_passes: int,
        market_pages_per_run: int,
        market_max_pages: int,
    ) -> dict:
        self.ledger.start_run(
            run_id,
            mode,
            focus,
            cache_policy,
            verification_passes,
        )
        try:
            result = self._execute_mode(
                mode,
                focus,
                wallet,
                cache_policy=cache_policy,
                run_id=run_id,
                market_pages_per_run=market_pages_per_run,
                market_max_pages=market_max_pages,
            )
            result["run_id"] = run_id
            result["cache_policy"] = cache_policy
            result["quality_architecture"] = QUALITY_ARCHITECTURE_VERSION
            self._record_signal_evidence(run_id, result)
            status = "COMPLETED" if result.get("ok") else "COMPLETED_WITH_SOURCE_ERROR"
            self.ledger.finish_run(run_id, status, result=result)
            return result
        except Exception as exc:
            self.ledger.finish_run(run_id, "FAILED", error=str(exc))
            raise

    def _execute_mode(
        self,
        mode: str,
        focus: str | None,
        wallet: str | None,
        *,
        cache_policy: str,
        run_id: str,
        market_pages_per_run: int,
        market_max_pages: int,
    ) -> dict:
        if mode == "confluence":
            if not focus:
                raise ValueError("confluence requires focus.")
            whale = self._run_single(
                "whale",
                focus,
                None,
                cache_policy=cache_policy,
                run_id=f"{run_id}-whale",
            )
            rotation = self._run_single(
                "rotation",
                focus,
                None,
                cache_policy=cache_policy,
                run_id=f"{run_id}-rotation",
            )
            source_status = self._merge_source_status(whale, rotation)
            source_errors = self._merge_source_errors(whale, rotation)
            degraded = bool(whale.get("degraded") or rotation.get("degraded"))
            confluence = self._build_confluence(focus, whale, rotation)
            ok = bool(whale.get("ok") and rotation.get("ok"))
            decision_eligible = bool(
                ok
                and not degraded
                and whale.get("decision_eligible")
                and rotation.get("decision_eligible")
                and confluence.get("verdict") == "strong_confluence"
            )
            return {
                "schema_version": OPENCLAW_SCHEMA_VERSION,
                "engine_version": SIGNAL_ENGINE_VERSION,
                "generated_at": self._now(),
                "ok": ok,
                "degraded": degraded,
                "decision_eligible": decision_eligible,
                "mode": "confluence",
                "focus": focus,
                "source_status": source_status,
                "source_errors": source_errors,
                "confluence": confluence,
                "legs": {"whale": whale, "rotation": rotation},
            }

        return self._run_single(
            mode,
            focus,
            wallet,
            cache_policy=cache_policy,
            run_id=run_id,
            market_pages_per_run=market_pages_per_run,
            market_max_pages=market_max_pages,
        )

    def _run_single(
        self,
        mode: str,
        focus: str | None,
        wallet: str | None,
        *,
        cache_policy: str,
        run_id: str,
        market_pages_per_run: int = 3,
        market_max_pages: int = 25,
    ) -> dict:
        etherscan = PersistentEtherscanSource(
            run_id=run_id,
            cache_policy=cache_policy,
            ledger=self.ledger,
        )
        market = FreshCoinGeckoSource(cache_policy=cache_policy)
        wallet_service = WalletService(etherscan)
        signal_engine = WhaleSignalEngineV3(etherscan, market)
        message_service = MessageService(wallet_service, signal_engine)

        data: dict = {}
        response_text = ""
        if mode == "wallet":
            target = (wallet or focus or "").strip()
            if not is_ethereum_wallet(target):
                raise ValueError("wallet mode requires a valid Ethereum 0x address.")
            command = target
            data = wallet_service.get_wallet_snapshot(target)
            response_text = wallet_service.format_wallet_snapshot(data)
        elif mode == "universe":
            command = "scan universe"
            data = MarketUniverseService(
                market,
                run_id=run_id,
                ledger=self.ledger,
            ).scan(
                pages_per_run=market_pages_per_run,
                max_pages=market_max_pages,
            )
            response_text = (
                f"Market universe pages {data.get('coverage', {}).get('completed_pages', [])}; "
                f"coins {data.get('coverage', {}).get('coins_scanned', 0)}."
            )
        else:
            if mode == "market":
                command = "scan gainers"
            elif mode == "rotation":
                command = f"scan rotation {focus}" if focus else "scan rotation"
            else:
                command = f"scan {focus}" if focus else "scan"

            response_text = message_service.handle_message(command)
            if mode == "whale":
                data = signal_engine.last_scan_snapshot
            elif mode == "rotation":
                data = signal_engine.rotation_engine.last_snapshot
            elif mode == "market":
                data = signal_engine.last_market_snapshot

        source_status = {}
        source_status.update(getattr(etherscan, "source_status", {}))
        source_status.update(getattr(market, "source_status", {}))
        source_errors = self._collect_source_errors(etherscan, market)
        degraded = self._is_degraded(source_status)
        data = self._apply_freshness_guard(mode, data, source_status)
        ok = self._result_ok(data, response_text)
        source_complete = bool(data.get("decision_eligible", True)) if isinstance(data, dict) else True
        decision_eligible = bool(ok and not degraded and source_complete)

        return {
            "schema_version": OPENCLAW_SCHEMA_VERSION,
            "engine_version": SIGNAL_ENGINE_VERSION,
            "generated_at": self._now(),
            "ok": ok,
            "degraded": degraded,
            "decision_eligible": decision_eligible,
            "mode": mode,
            "focus": focus,
            "command": command,
            "source_status": source_status,
            "source_errors": source_errors,
            "cache": {
                "market": market.cache_diagnostics(),
                "etherscan": etherscan.cache_diagnostics(),
            },
            "data": data,
            "response_text": response_text,
        }

    @staticmethod
    def _apply_freshness_guard(
        mode: str,
        data: dict,
        source_status: dict[str, str],
    ) -> dict:
        guarded = copy.deepcopy(data) if isinstance(data, dict) else {}
        stale = any(
            str(status).startswith("stale_cache_")
            or str(status).startswith("circuit_open_")
            for status in source_status.values()
        )
        guarded["freshness"] = "stale_or_circuit" if stale else "fresh_or_live"
        guarded["freshness_eligible"] = not stale
        if not stale:
            return guarded

        guarded["decision_eligible"] = False
        warnings = guarded.setdefault("quality_warnings", [])
        if "stale_market_data_not_decision_eligible" not in warnings:
            warnings.append("stale_market_data_not_decision_eligible")

        if mode == "whale":
            for signal in guarded.get("signals") or []:
                if signal.get("classification") == "actionable":
                    signal["classification"] = "context"
                if signal.get("quality_tier") in {"actionable", "confirmed"}:
                    signal["quality_tier"] = "interesting"
                flags = signal.setdefault("quality_flags", [])
                if "stale_market_context" not in flags:
                    flags.append("stale_market_context")
            summary = guarded.get("summary")
            if isinstance(summary, dict):
                summary["actionable"] = 0
        return guarded

    @staticmethod
    def _collect_source_errors(etherscan, market) -> list[str]:
        errors: list[str] = []
        etherscan_error = getattr(etherscan, "last_error", None)
        if etherscan_error:
            errors.append(str(etherscan_error))
        for error in getattr(market, "last_errors", []):
            text = str(error)
            if text and text not in errors:
                errors.append(text)
        return errors

    @staticmethod
    def _is_degraded(source_status: dict[str, str]) -> bool:
        acceptable = {"ok", "ok_cached", "not_used", "cached_unavailable"}
        return any(status not in acceptable for status in source_status.values())

    @staticmethod
    def _merge_source_status(*results: dict) -> dict[str, str]:
        merged: dict[str, str] = {}
        for result in results:
            for source, status in (result.get("source_status") or {}).items():
                existing = merged.get(source)
                if existing is None or existing in {"ok", "ok_cached", "not_used"}:
                    merged[source] = status
        return merged

    @staticmethod
    def _merge_source_errors(*results: dict) -> list[str]:
        merged: list[str] = []
        for result in results:
            for error in result.get("source_errors") or []:
                text = str(error)
                if text and text not in merged:
                    merged.append(text)
        return merged

    @staticmethod
    def _result_ok(data: dict, response_text: str) -> bool:
        structured_ok = data.get("ok") if isinstance(data, dict) else None
        if isinstance(structured_ok, bool):
            return structured_ok
        return OpenClawService._response_ok(response_text)

    @staticmethod
    def _build_confluence(focus: str, whale: dict, rotation: dict) -> dict:
        whale_rows = (whale.get("data") or {}).get("signals") or []
        rotation_rows = (rotation.get("data") or {}).get("top_candidates") or []

        def matches(row: dict) -> bool:
            values = [
                str(row.get("symbol", "")).lower(),
                str(row.get("name", "")).lower(),
                str(row.get("contract", "")).lower(),
            ]
            return any(focus in value for value in values if value)

        whale_match = next((row for row in whale_rows if matches(row)), None)
        rotation_match = next((row for row in rotation_rows if matches(row)), None)
        whale_level = str((whale_match or {}).get("quality_tier", "none"))
        rotation_status = str((rotation_match or {}).get("status", "none"))
        degraded = bool(whale.get("degraded") or rotation.get("degraded"))
        freshness_eligible = bool(
            (whale.get("data") or {}).get("freshness_eligible", True)
            and (rotation.get("data") or {}).get("freshness_eligible", True)
        )

        strong_whale = whale_level in {"confirmed", "actionable"}
        strong_rotation = rotation_status in {"momentum rotation", "outperforming"}
        if degraded or not freshness_eligible:
            if whale_match or rotation_match:
                verdict = "degraded_confluence_context"
            else:
                verdict = "no_confluence"
        elif strong_whale and strong_rotation:
            verdict = "strong_confluence"
        elif whale_match and rotation_match:
            verdict = "partial_confluence"
        elif whale_match:
            verdict = "whale_only"
        elif rotation_match:
            verdict = "rotation_only"
        else:
            verdict = "no_confluence"

        return {
            "verdict": verdict,
            "decision_eligible": verdict == "strong_confluence",
            "freshness_eligible": freshness_eligible,
            "whale_detected": whale_match is not None,
            "rotation_detected": rotation_match is not None,
            "whale_signal": whale_match,
            "rotation_signal": rotation_match,
        }

    def _record_signal_evidence(self, run_id: str, result: dict) -> None:
        quality = "degraded" if result.get("degraded") else "fresh"
        if result.get("mode") == "whale":
            self.ledger.record_signal_snapshot(run_id, result.get("data") or {}, quality)
        elif result.get("mode") == "confluence":
            whale_data = ((result.get("legs") or {}).get("whale") or {}).get("data") or {}
            self.ledger.record_signal_snapshot(run_id, whale_data, quality)

    @staticmethod
    def _verification_summary(mode: str, results: list[dict]) -> dict:
        signatures = [OpenClawService._result_signature(mode, result) for result in results]
        successful = [result for result in results if result.get("ok")]
        unique = {repr(signature) for signature in signatures}
        if len(successful) != len(results):
            status = "insufficient"
        elif len(unique) == 1:
            status = "confirmed"
        else:
            status = "divergent"
        return {
            "status": status,
            "passes": len(results),
            "successful_passes": len(successful),
            "agreement_ratio": round(max(signatures.count(item) for item in signatures) / len(signatures), 3),
            "signatures": signatures,
            "policies": [result.get("cache_policy") for result in results],
        }

    @staticmethod
    def _result_signature(mode: str, result: dict):
        if mode == "confluence":
            return (
                (result.get("confluence") or {}).get("verdict"),
                OpenClawService._result_signature(
                    "whale",
                    ((result.get("legs") or {}).get("whale") or {}),
                ),
                OpenClawService._result_signature(
                    "rotation",
                    ((result.get("legs") or {}).get("rotation") or {}),
                ),
            )
        data = result.get("data") or {}
        if mode == "whale":
            return tuple(sorted(
                (
                    row.get("contract"),
                    row.get("direction"),
                    row.get("quality_tier"),
                )
                for row in data.get("signals") or []
            ))
        if mode in {"rotation", "universe"}:
            return tuple(
                (row.get("symbol"), row.get("status"))
                for row in (data.get("top_candidates") or [])[:10]
            )
        if mode == "market":
            return tuple(row.get("symbol") for row in (data.get("movers") or [])[:10])
        if mode == "wallet":
            return (
                data.get("wallet"),
                data.get("balance_eth"),
                tuple(row.get("hash") for row in data.get("transactions") or []),
            )
        return repr(data)

    @staticmethod
    def _validate_request(mode: str, cache_policy: str, verification_passes: int) -> None:
        if mode not in OpenClawService.ALLOWED_MODES:
            raise ValueError(
                f"Unsupported mode '{mode}'. Allowed: "
                f"{', '.join(sorted(OpenClawService.ALLOWED_MODES))}."
            )
        if cache_policy not in CACHE_POLICIES:
            raise ValueError(
                f"Unsupported cache_policy '{cache_policy}'. Allowed: "
                f"{', '.join(sorted(CACHE_POLICIES))}."
            )
        if verification_passes < 1 or verification_passes > 3:
            raise ValueError("verification_passes must be between 1 and 3.")
        if mode == "universe" and verification_passes > 1:
            raise ValueError(
                "universe mode advances rolling coverage and therefore supports one pass per request; "
                "submit additional fresh jobs for independent market segments."
            )

    @staticmethod
    def _response_ok(response_text: str) -> bool:
        lowered = response_text.lower()
        hard_failures = (
            "status: scan_failed",
            "status: api_failed",
            "status: rotation_failed",
            "scan fehlgeschlagen.",
            "braucht eine eigene",
        )
        return not any(marker in lowered for marker in hard_failures)

    @staticmethod
    def _now() -> str:
        return datetime.now(timezone.utc).isoformat()
