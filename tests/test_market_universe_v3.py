from services.evidence_ledger import EvidenceLedger
from services.market_universe_service import MarketUniverseService


class FakeMarketSource:
    def __init__(self):
        self.calls = []

    def get_market_page(self, page: int = 1, per_page: int = 100):
        self.calls.append(page)
        if page == 1:
            return [
                {
                    "name": "Bitcoin",
                    "symbol": "BTC",
                    "change_24h": 1.0,
                    "change_7d": 2.0,
                    "volume_24h": 10_000_000,
                    "market_cap": 1_000_000_000,
                },
                {
                    "name": "Ethereum",
                    "symbol": "ETH",
                    "change_24h": 1.5,
                    "change_7d": 3.0,
                    "volume_24h": 8_000_000,
                    "market_cap": 500_000_000,
                },
            ]
        return [
            {
                "name": f"Coin {page}",
                "symbol": f"C{page}",
                "change_24h": float(page),
                "change_7d": float(page * 2),
                "volume_24h": 2_000_000,
                "market_cap": 20_000_000,
            }
        ]


def test_market_universe_rolls_cursor_without_duplicate_page_one(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    source = FakeMarketSource()
    result = MarketUniverseService(
        source,
        run_id="universe-1",
        ledger=ledger,
    ).scan(pages_per_run=3, max_pages=5)

    assert result["ok"] is True
    assert result["coverage"]["completed_pages"] == [1, 2, 3]
    assert source.calls.count(1) == 1
    assert ledger.get_int_checkpoint("market_universe:last_page") == 3


def test_market_universe_continues_next_segment(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    ledger.set_checkpoint("market_universe:last_page", 3)
    source = FakeMarketSource()
    result = MarketUniverseService(
        source,
        run_id="universe-2",
        ledger=ledger,
    ).scan(pages_per_run=2, max_pages=5)

    assert result["coverage"]["completed_pages"] == [4, 5]
    assert ledger.get_int_checkpoint("market_universe:last_page") == 5
