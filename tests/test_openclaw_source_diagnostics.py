from services.openclaw_service import OpenClawService
from sources.etherscan_source import EtherscanSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource


def test_source_errors_are_exposed_without_duplicates():
    etherscan = EtherscanSource()
    market = FreshCoinGeckoSource()
    etherscan.last_error = "Etherscan timeout: request timed out (3 attempts)"
    market.last_errors = [
        "CoinGecko rate_limit: HTTP 429 (3 attempts)",
        "CoinGecko rate_limit: HTTP 429 (3 attempts)",
    ]

    assert OpenClawService._collect_source_errors(etherscan, market) == [
        "Etherscan timeout: request timed out (3 attempts)",
        "CoinGecko rate_limit: HTTP 429 (3 attempts)",
    ]


def test_stale_cache_status_is_marked_degraded():
    assert OpenClawService._is_degraded(
        {
            "Etherscan": "not_used",
            "CoinGecko": "stale_cache_rate_limit",
            "DexScreener": "not_used",
        }
    ) is True


def test_cached_success_is_not_marked_degraded():
    assert OpenClawService._is_degraded(
        {
            "Etherscan": "not_used",
            "CoinGecko": "ok_cached",
            "DexScreener": "not_used",
        }
    ) is False
