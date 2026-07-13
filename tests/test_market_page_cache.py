import time
from unittest.mock import patch

from sources.coingecko_source import CoinGeckoSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource


def test_market_page_cache_reuses_rows_across_request_instances():
    FreshCoinGeckoSource.clear_shared_cache()
    rows = [{"symbol": "BTC", "price": 1.0}]

    with patch.object(CoinGeckoSource, "get_market_page", return_value=rows) as mocked:
        first = FreshCoinGeckoSource()
        second = FreshCoinGeckoSource()

        assert first.get_market_page(page=1, per_page=100) == rows
        assert second.get_market_page(page=1, per_page=100) == rows
        assert mocked.call_count == 1
        assert second.page_cache_hits == 1
        assert second.source_status["CoinGecko"] == "ok_cached"


def test_stale_market_page_is_used_after_rate_limit():
    FreshCoinGeckoSource.clear_shared_cache()
    rows = [{"symbol": "BTC", "price": 1.0}]
    now = time.monotonic()
    FreshCoinGeckoSource._shared_page_cache[(1, 100)] = (
        now - 1,
        now + 60,
        rows,
    )

    source = FreshCoinGeckoSource()
    source.source_status["CoinGecko"] = "rate_limit"

    with patch.object(CoinGeckoSource, "get_market_page", return_value=[]):
        result = source.get_market_page(page=1, per_page=100)

    assert result == rows
    assert source.source_status["CoinGecko"] == "stale_cache_rate_limit"
    assert source.page_stale_fallbacks == 1
    assert source.cache_diagnostics()["market_page_stale_fallbacks"] == 1
