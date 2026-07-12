from __future__ import annotations

from datetime import datetime, timezone

from config.settings import OPENCLAW_SCHEMA_VERSION, SIGNAL_ENGINE_VERSION
from services.message_service import MessageService
from services.signal_engine_v2 import WhaleSignalEngineV2
from services.wallet_service import WalletService
from sources.etherscan_source import EtherscanSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource
from utils.text_utils import is_ethereum_wallet


class OpenClawService:
    """Stable machine-facing adapter for OpenClaw and future agents."""

    ALLOWED_MODES = {"whale", "market", "rotation", "confluence", "wallet"}

    @staticmethod
    def capabilities() -> dict:
        return {
            "schema_version": OPENCLAW_SCHEMA_VERSION,
            "engine_version": SIGNAL_ENGINE_VERSION,
            "modes": {
                "whale": "Real Ethereum ERC-20 transfer-cluster scan.",
                "market": "Price/volume movers from CoinGecko with DexScreener fallback.",
                "rotation": "Relative strength versus BTC, ETH and broad alt-market proxy.",
                "confluence": "Focused whale scan plus focused rotation scan in one response.",
                "wallet": "Ethereum wallet balance and recent transactions.",
            },
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
                "Ethereum scan coverage is a current Etherscan sample, not full-chain coverage.",
                "SUI and PLUME need dedicated chain/explorer sources.",
                "Portfolio bonus is reported separately and cannot establish actionability.",
            ],
        }

    def execute(self, mode: str, focus: str | None = None, wallet: str | None = None) -> dict:
        normalized_mode = mode.strip().lower()
        normalized_focus = focus.strip().lower() if focus and focus.strip() else None
        if normalized_mode not in self.ALLOWED_MODES:
            raise ValueError(
                f"Unsupported mode '{mode}'. Allowed: {', '.join(sorted(self.ALLOWED_MODES))}."
            )

        if normalized_mode == "confluence":
            if not normalized_focus:
                raise ValueError("confluence requires focus.")
            whale = self._run_single("whale", normalized_focus, None)
            rotation = self._run_single("rotation", normalized_focus, None)
            confluence = self._build_confluence(normalized_focus, whale, rotation)
            return {
                "schema_version": OPENCLAW_SCHEMA_VERSION,
                "engine_version": SIGNAL_ENGINE_VERSION,
                "generated_at": self._now(),
                "ok": whale["ok"] and rotation["ok"],
                "mode": "confluence",
                "focus": normalized_focus,
                "confluence": confluence,
                "legs": {
                    "whale": whale,
                    "rotation": rotation,
                },
            }

        return self._run_single(normalized_mode, normalized_focus, wallet)

    def _run_single(self, mode: str, focus: str | None, wallet: str | None) -> dict:
        etherscan = EtherscanSource()
        market = FreshCoinGeckoSource()
        wallet_service = WalletService(etherscan)
        signal_engine = WhaleSignalEngineV2(etherscan, market)
        message_service = MessageService(wallet_service, signal_engine)

        if mode == "wallet":
            target = (wallet or focus or "").strip()
            if not is_ethereum_wallet(target):
                raise ValueError("wallet mode requires a valid Ethereum 0x address.")
            command = target
        elif mode == "market":
            command = "scan gainers"
        elif mode == "rotation":
            command = f"scan rotation {focus}" if focus else "scan rotation"
        else:
            command = f"scan {focus}" if focus else "scan"

        response_text = message_service.handle_message(command)
        source_status = {}
        source_status.update(getattr(etherscan, "source_status", {}))
        source_status.update(getattr(market, "source_status", {}))

        data: dict = {}
        if mode == "whale":
            data = signal_engine.last_scan_snapshot
        elif mode == "rotation":
            data = signal_engine.rotation_engine.last_snapshot
        elif mode == "market":
            data = signal_engine.last_market_snapshot

        return {
            "schema_version": OPENCLAW_SCHEMA_VERSION,
            "engine_version": SIGNAL_ENGINE_VERSION,
            "generated_at": self._now(),
            "ok": self._response_ok(response_text),
            "mode": mode,
            "focus": focus,
            "command": command,
            "source_status": source_status,
            "cache": market.cache_diagnostics(),
            "data": data,
            "response_text": response_text,
        }

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

        strong_whale = whale_level in {"confirmed", "actionable"}
        strong_rotation = rotation_status in {"momentum rotation", "outperforming"}
        if strong_whale and strong_rotation:
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
            "whale_detected": whale_match is not None,
            "rotation_detected": rotation_match is not None,
            "whale_signal": whale_match,
            "rotation_signal": rotation_match,
        }

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
