from app import create_app
from config.settings import OPENCLAW_SCHEMA_VERSION, SIGNAL_ENGINE_VERSION
from models.api_models import OpenClawScanRequest
from routes import control_plane_routes, message_routes
from services.openclaw_service import OpenClawService


def test_control_plane_routes_are_registered_before_scan_routes():
    app = create_app()
    included = [route.original_router for route in app.routes if hasattr(route, "original_router")]
    assert len(included) == 2
    control_paths = [route.path for route in included[0].routes]
    scan_paths = [route.path for route in included[1].routes]
    assert "/healthz" in control_paths
    assert "/health" in control_paths
    assert "/openclaw/capabilities" in control_paths
    assert "/capabilities" in control_paths
    assert "/openclaw/scan" in scan_paths


def test_healthz_uses_local_contract_without_external_http(monkeypatch):
    calls = []

    def forbidden_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("control plane must not call external HTTP")

    monkeypatch.setattr("utils.http_client.requests.get", forbidden_get)

    payload = control_plane_routes.healthz()

    assert payload["ok"] is True
    assert payload["status"] == "ok"
    assert payload["service"] == "whale-signal-bot"
    assert payload["engine_version"] == SIGNAL_ENGINE_VERSION
    assert payload["schema_version"] == OPENCLAW_SCHEMA_VERSION
    assert payload["openclaw_schema"] == OPENCLAW_SCHEMA_VERSION
    assert payload["ready"] is True
    assert payload["scan_worker_available"] is True
    assert payload["request_id"].startswith("whalebot-control-")
    assert payload["elapsed_ms"] >= 0
    assert calls == []


def test_compat_health_uses_same_fast_control_plane(monkeypatch):
    calls = []

    def forbidden_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("control plane must not call external HTTP")

    monkeypatch.setattr("utils.http_client.requests.get", forbidden_get)

    payload = control_plane_routes.health()

    assert payload["ok"] is True
    assert payload["engine_version"] == SIGNAL_ENGINE_VERSION
    assert payload["schema_version"] == OPENCLAW_SCHEMA_VERSION
    assert calls == []


def test_openclaw_capabilities_are_static_and_preserve_existing_contract(monkeypatch):
    calls = []

    def forbidden_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("control plane must not call external HTTP")

    monkeypatch.setattr("utils.http_client.requests.get", forbidden_get)

    payload = control_plane_routes.openclaw_capabilities()

    existing = OpenClawService.capabilities()
    assert payload["ok"] is True
    assert payload["schema_version"] == existing["schema_version"]
    assert payload["engine_version"] == existing["engine_version"]
    assert payload["modes"] == existing["modes"]
    assert payload["commands"] == existing["commands"]
    assert payload["limitations"] == existing["limitations"]
    assert payload["signals"] == []
    assert payload["market_data"] == []
    assert payload["safety"]["creates_order"] is False
    assert payload["safety"]["creates_paper_entry"] is False
    assert payload["safety"]["executes_live"] is False
    assert calls == []


def test_compat_capabilities_uses_same_fast_control_plane(monkeypatch):
    calls = []

    def forbidden_get(*args, **kwargs):
        calls.append((args, kwargs))
        raise AssertionError("control plane must not call external HTTP")

    monkeypatch.setattr("utils.http_client.requests.get", forbidden_get)

    payload = control_plane_routes.capabilities()

    assert payload["ok"] is True
    assert payload["engine_version"] == SIGNAL_ENGINE_VERSION
    assert payload["schema_version"] == OPENCLAW_SCHEMA_VERSION
    assert "confluence" in payload["modes"]
    assert calls == []


def test_openclaw_scan_route_still_delegates_to_existing_service(monkeypatch):
    captured = {}

    def fake_execute(self, mode, focus=None, wallet=None):
        captured.update({"mode": mode, "focus": focus, "wallet": wallet})
        return {
            "schema_version": OPENCLAW_SCHEMA_VERSION,
            "engine_version": SIGNAL_ENGINE_VERSION,
            "ok": True,
            "mode": mode,
            "focus": focus,
            "source_status": {},
            "source_errors": [],
            "cache": {},
            "data": {"ok": True, "signals": []},
        }

    monkeypatch.setattr(OpenClawService, "execute", fake_execute)

    response = message_routes.openclaw_scan(
        OpenClawScanRequest(mode="confluence", focus="candidate_symbol")
    )

    assert captured == {"mode": "confluence", "focus": "candidate_symbol", "wallet": None}
    assert response["schema_version"] == OPENCLAW_SCHEMA_VERSION
