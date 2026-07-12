import pytest

from services.openclaw_service import OpenClawService


def test_capabilities_expose_confluence_and_schema():
    capabilities = OpenClawService.capabilities()
    assert "confluence" in capabilities["modes"]
    assert capabilities["schema_version"].startswith("whalebot.openclaw.")


def test_unknown_mode_is_rejected_before_network_calls():
    with pytest.raises(ValueError):
        OpenClawService().execute("unknown")


def test_confluence_marks_matching_strong_signals():
    whale = {
        "data": {
            "signals": [
                {
                    "symbol": "ONDO",
                    "name": "Ondo",
                    "contract": "0x123",
                    "quality_tier": "actionable",
                }
            ]
        }
    }
    rotation = {
        "data": {
            "top_candidates": [
                {
                    "symbol": "ONDO",
                    "name": "Ondo",
                    "status": "outperforming",
                }
            ]
        }
    }
    result = OpenClawService._build_confluence("ondo", whale, rotation)
    assert result["verdict"] == "strong_confluence"
