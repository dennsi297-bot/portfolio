from unittest.mock import patch

from models.domain_models import MarketContext
from sources.coingecko_source import CoinGeckoSource
from sources.fresh_coingecko_source import FreshCoinGeckoSource


def test_shared_ttl_cache_reuses_market_context_across_request_instances():
    FreshCoinGeckoSource.clear_shared_cache()
    context = MarketContext(
        token_name="Test",
        token_symbol="TST",
        current_price_usd=1.0,
        available=True,
    )

    with patch.object(CoinGeckoSource, "get_market_context", return_value=context) as mocked:
        first = FreshCoinGeckoSource()
        second = FreshCoinGeckoSource()
        assert first.get_market_context("0xabc") is context
        assert second.get_market_context("0xabc") is context
        assert mocked.call_count == 1
        assert second.cache_hits == 1
