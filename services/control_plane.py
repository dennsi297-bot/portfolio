from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timezone
from typing import Any

from config.settings import (
    OPENCLAW_SCHEMA_VERSION,
    SIGNAL_ENGINE_VERSION,
    get_etherscan_api_key,
)


SERVICE_NAME = "whale-signal-bot"
PROCESS_STARTED_AT = datetime.now(timezone.utc).isoformat()
BUILD_COMMIT = (
    os.getenv("RENDER_GIT_COMMIT")
    or os.getenv("GIT_COMMIT")
    or os.getenv("SOURCE_VERSION")
    or "UNKNOWN"
)

CAPABILITY_MANIFEST: dict[str, Any] = {
    "schema_version": OPENCLAW_SCHEMA_VERSION,
    "engine_version": SIGNAL_ENGINE_VERSION,
    "modes": {
        "whale": "Real Ethereum ERC-20 transfer-cluster scan.",
        "market": "Price/volume movers from CoinGecko with DexScreener fallback.",
        "rotation": "Relative strength versus BTC, ETH and broad alt-market proxy.",
        "confluence": "Focused whale scan plus focused rotation scan in one response.",
        "wallet": "Structured Ethereum wallet balance and recent transactions.",
    },
    "supported_parameters": {
        "whale": {"focus": "optional symbol or contract"},
        "market": {},
        "rotation": {"focus": "optional symbol"},
        "confluence": {"focus": "required symbol or contract"},
        "wallet": {"wallet": "required Ethereum address"},
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
    "safety": {
        "creates_order": False,
        "creates_paper_entry": False,
        "executes_live": False,
        "mutates_portfolio": False,
        "report_only": True,
    },
    "hard_forbidden_actions": [
        "create_order",
        "execute_live",
        "create_paper_entry",
        "call_exchange",
        "mutate_portfolio",
    ],
    "signals": [],
    "market_data": [],
}


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _with_control_telemetry(payload: dict[str, Any], response_started_at: str | None = None) -> dict[str, Any]:
    started_perf = time.perf_counter()
    started_at = response_started_at or utc_now()
    result = dict(payload)
    result.setdefault("request_id", f"whalebot-control-{uuid.uuid4().hex[:16]}")
    result.setdefault("service_started_at", PROCESS_STARTED_AT)
    result.setdefault("process_started_at", PROCESS_STARTED_AT)
    result.setdefault("response_started_at", started_at)
    result.setdefault("engine_version", SIGNAL_ENGINE_VERSION)
    result.setdefault("schema_version", OPENCLAW_SCHEMA_VERSION)
    result.setdefault("openclaw_schema", OPENCLAW_SCHEMA_VERSION)
    result.setdefault("build_commit", BUILD_COMMIT)
    result["response_finished_at"] = utc_now()
    result["elapsed_ms"] = round((time.perf_counter() - started_perf) * 1000, 3)
    return result


def health_payload() -> dict[str, Any]:
    return _with_control_telemetry(
        {
            "ok": True,
            "status": "ok",
            "service": SERVICE_NAME,
            "current_timestamp": utc_now(),
            "ready": True,
            "scan_worker_available": True,
            "etherscan_configured": bool(get_etherscan_api_key()),
        }
    )


def capabilities_payload() -> dict[str, Any]:
    payload = dict(CAPABILITY_MANIFEST)
    payload.update(
        {
            "ok": True,
            "status": "ok",
            "service": SERVICE_NAME,
            "ready": True,
            "scan_worker_available": True,
        }
    )
    return _with_control_telemetry(payload)
