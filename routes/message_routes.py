import uuid

from fastapi import APIRouter, HTTPException, status

from config.settings import DEFAULT_CACHE_POLICY, OPENCLAW_SCHEMA_VERSION, SIGNAL_ENGINE_VERSION
from models.api_models import MessageRequest, OpenClawScanRequest
from services.evidence_ledger import get_evidence_ledger
from services.message_service import MessageService
from services.openclaw_service import OpenClawService
from services.scan_job_service import get_scan_job_service
from services.signal_engine_v3 import WhaleSignalEngineV3
from services.wallet_service import WalletService
from sources.fresh_coingecko_source import FreshCoinGeckoSource
from sources.persistent_etherscan_source import PersistentEtherscanSource


router = APIRouter()


def _build_message_service() -> MessageService:
    run_id = f"whalebot-message-{uuid.uuid4().hex[:16]}"
    ledger = get_evidence_ledger()
    etherscan_source = PersistentEtherscanSource(
        run_id=run_id,
        cache_policy=DEFAULT_CACHE_POLICY,
        ledger=ledger,
    )
    coingecko_source = FreshCoinGeckoSource(cache_policy=DEFAULT_CACHE_POLICY)
    wallet_service = WalletService(etherscan_source)
    signal_engine = WhaleSignalEngineV3(etherscan_source, coingecko_source)
    return MessageService(wallet_service, signal_engine)


def _request_payload(request: OpenClawScanRequest) -> dict:
    if hasattr(request, "model_dump"):
        return request.model_dump()
    return request.dict()


@router.get("/")
def read_root():
    return {
        "message": "Bot laeuft",
        "engine_version": SIGNAL_ENGINE_VERSION,
        "openclaw_schema": OPENCLAW_SCHEMA_VERSION,
    }


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
            cache_policy=request.cache_policy,
            verification_passes=request.verification_passes,
            market_pages_per_run=request.market_pages_per_run,
            market_max_pages=request.market_max_pages,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.post("/openclaw/jobs", status_code=status.HTTP_202_ACCEPTED)
def create_openclaw_job(request: OpenClawScanRequest):
    try:
        OpenClawService._validate_request(
            request.mode.strip().lower(),
            request.cache_policy,
            request.verification_passes,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return get_scan_job_service().submit(_request_payload(request))


@router.get("/openclaw/jobs/{job_id}")
def get_openclaw_job(job_id: str):
    job = get_scan_job_service().get(job_id)
    if job is None:
        raise HTTPException(status_code=404, detail="Unknown or expired job_id.")
    return job


@router.get("/openclaw/evidence/{run_id}")
def get_openclaw_evidence(run_id: str):
    evidence = get_evidence_ledger().get_run(run_id)
    if evidence is None:
        raise HTTPException(status_code=404, detail="Unknown run_id.")
    return evidence
