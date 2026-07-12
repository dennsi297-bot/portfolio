from unittest.mock import patch

import pytest

from services.openclaw_service import OpenClawService
from sources.etherscan_source import EtherscanSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource


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


def test_market_failure_uses_structured_snapshot_status():
    with patch.object(FreshCoinGeckoSource, "get_market_movers", return_value=[]):
        result = OpenClawService().execute("market")

    assert result["ok"] is False
    assert result["data"]["ok"] is False
    assert result["data"]["movers"] == []


def test_wallet_mode_returns_structured_balance_and_transactions():
    wallet = "0x" + "1" * 40
    transactions = [
        {
            "from": wallet,
            "to": "0x" + "2" * 40,
            "value": str(10**18),
            "hash": "0xabcdef1234567890",
            "timeStamp": "123456",
            "isError": "0",
        }
    ]

    with (
        patch.object(EtherscanSource, "get_eth_balance", return_value="1.500000 ETH"),
        patch.object(EtherscanSource, "get_wallet_transactions", return_value=transactions),
    ):
        result = OpenClawService().execute("wallet", wallet=wallet)

    assert result["ok"] is True
    assert result["data"]["wallet"] == wallet
    assert result["data"]["balance_eth"] == 1.5
    assert result["data"]["transactions"][0]["direction"] == "Ausgang"
    assert result["data"]["transactions"][0]["value_eth"] == 1.0
