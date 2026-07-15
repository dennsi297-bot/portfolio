from fastapi import APIRouter

from services.control_plane import capabilities_payload, health_payload


router = APIRouter()


@router.get("/healthz")
def healthz():
    return health_payload()


@router.get("/health")
def health():
    return health_payload()


@router.get("/openclaw/capabilities")
def openclaw_capabilities():
    return capabilities_payload()


@router.get("/capabilities")
def capabilities():
    return capabilities_payload()
