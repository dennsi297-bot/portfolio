import pytest

from services.evidence_ledger import EvidenceLedger
from services.openclaw_service import OpenClawService


def test_stale_whale_context_cannot_remain_actionable():
    data = {
        "ok": True,
        "summary": {"actionable": 1},
        "signals": [
            {
                "symbol": "ONDO",
                "classification": "actionable",
                "quality_tier": "actionable",
                "quality_flags": [],
            }
        ],
    }
    guarded = OpenClawService._apply_freshness_guard(
        "whale",
        data,
        {"CoinGecko": "stale_cache_rate_limit"},
    )
    signal = guarded["signals"][0]
    assert guarded["decision_eligible"] is False
    assert guarded["freshness_eligible"] is False
    assert guarded["summary"]["actionable"] == 0
    assert signal["classification"] == "context"
    assert signal["quality_tier"] == "interesting"
    assert "stale_market_context" in signal["quality_flags"]


def test_degraded_rotation_cannot_create_strong_confluence():
    whale = {
        "ok": True,
        "degraded": False,
        "decision_eligible": True,
        "data": {
            "freshness_eligible": True,
            "signals": [
                {
                    "symbol": "ONDO",
                    "name": "Ondo",
                    "contract": "0x123",
                    "quality_tier": "actionable",
                }
            ],
        },
    }
    rotation = {
        "ok": True,
        "degraded": True,
        "decision_eligible": False,
        "data": {
            "freshness_eligible": False,
            "top_candidates": [
                {
                    "symbol": "ONDO",
                    "name": "Ondo",
                    "status": "outperforming",
                }
            ],
        },
    }
    result = OpenClawService._build_confluence("ondo", whale, rotation)
    assert result["verdict"] == "degraded_confluence_context"
    assert result["decision_eligible"] is False


def test_verification_marks_identical_passes_confirmed():
    results = [
        {
            "ok": True,
            "cache_policy": "fresh_required",
            "data": {
                "signals": [
                    {
                        "contract": "0x123",
                        "direction": "accumulation",
                        "quality_tier": "confirmed",
                    }
                ]
            },
        },
        {
            "ok": True,
            "cache_policy": "audit_refresh",
            "data": {
                "signals": [
                    {
                        "contract": "0x123",
                        "direction": "accumulation",
                        "quality_tier": "confirmed",
                    }
                ]
            },
        },
    ]
    verification = OpenClawService._verification_summary("whale", results)
    assert verification["status"] == "confirmed"
    assert verification["agreement_ratio"] == 1.0


def test_multi_pass_result_has_persisted_parent_evidence(tmp_path, monkeypatch):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    service = OpenClawService(ledger=ledger)

    def fake_execute_once(
        mode,
        focus,
        wallet,
        *,
        cache_policy,
        run_id,
        verification_passes,
        market_pages_per_run,
        market_max_pages,
    ):
        return {
            "ok": True,
            "mode": mode,
            "decision_eligible": True,
            "run_id": run_id,
            "cache_policy": cache_policy,
            "data": {"signals": []},
        }

    monkeypatch.setattr(service, "_execute_once", fake_execute_once)
    result = service.execute(
        "whale",
        verification_passes=2,
        run_id="aggregate-run",
    )

    evidence = ledger.get_run("aggregate-run")
    assert evidence is not None
    assert evidence["status"] == "COMPLETED"
    assert evidence["result"]["run_id"] == "aggregate-run"
    assert evidence["result"]["child_run_ids"] == [
        "aggregate-run-p1",
        "aggregate-run-p2",
    ]
    assert result["verification"]["status"] == "confirmed"


def test_universe_verification_requires_separate_jobs():
    with pytest.raises(ValueError, match="one pass per request"):
        OpenClawService._validate_request(
            "universe",
            "fresh_required",
            2,
        )
