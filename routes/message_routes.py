from fastapi import APIRouter, HTTPException

from config.settings import OPENCLAW_SCHEMA_VERSION, SIGNAL_ENGINE_VERSION
from models.api_models import MessageRequest, OpenClawScanRequest
from services.message_service import MessageService
from services.openclaw_service import OpenClawService
from services.signal_engine_v2 import WhaleSignalEngineV2
from services.wallet_service import WalletService
from sources.etherscan_source import EtherscanSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource


# Router module keeps HTTP wiring separate from scanner logic.
router = APIRouter()


def _build_message_service() -> MessageService:
    # Per-request source objects prevent source_status/last_error from leaking
    # between simultaneous scans. FreshCoinGeckoSource still provides a safe TTL cache.
    etherscan_source = EtherscanSource()
    coingecko_source = FreshCoinGeckoSource()
    wallet_service = WalletService(etherscan_source)
    signal_engine = WhaleSignalEngineV2(etherscan_source, coingecko_source)
    return MessageService(wallet_service, signal_engine)


@router.get("/")
def read_root():
    return {
        "message": "Bot laeuft",
        "engine_version": SIGNAL_ENGINE_VERSION,
        "openclaw_schema": OPENCLAW_SCHEMA_VERSION,
    }


@router.get("/health")
def health():
    etherscan_source = EtherscanSource()
    return {
        "ok": True,
        "service": "whale-signal-bot",
        "engine_version": SIGNAL_ENGINE_VERSION,
        "openclaw_schema": OPENCLAW_SCHEMA_VERSION,
        "etherscan_configured": etherscan_source.has_api_key(),
    }


@router.get("/capabilities")
def capabilities():
    return OpenClawService.capabilities()


@router.post("/message")
def handle_message(message: MessageRequest):
    service = _build_message_service()
    return {"response": service.handle_message(message.text)}


@router.post("/openclaw/scan")
def openclaw_scan(request: OpenClawScanRequest):
    try:
        return OpenClawService().execute(
            mode=request.mode,
            focus=request.focus,
            wallet=request.wallet,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
