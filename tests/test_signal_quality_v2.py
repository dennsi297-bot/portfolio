from models.domain_models import MarketContext, WhaleSignal
from services.signal_engine_v2 import WhaleSignalEngineV2


class DummySource:
    source_status = {}


class DummyMarket:
    source_status = {}

    def get_market_context(self, contract):
        return MarketContext(
            token_name="Ondo",
            token_symbol="ONDO",
            market_cap_rank=50,
            current_price_usd=1.0,
            volume_24h_usd=50_000_000,
            market_profile="major",
            available=True,
        )


def make_signal(**overrides):
    values = {
        "token_symbol": "ONDO",
        "token_name": "Ondo",
        "token_contract": "0x123",
        "direction": "accumulation",
        "wallet_addresses": [f"0x{i:040x}" for i in range(6)],
        "wallet_count": 6,
        "repeated_wallets": 2,
        "event_count": 8,
        "total_size": 100_000.0,
        "time_window": "test",
        "large_event_threshold": 1_000.0,
        "wallet_quality_score": 1.5,
        "token_relevance_score": 0.0,
        "directional_score": 0.8,
        "transfer_strength_score": 30.0,
        "confidence": "medium",
        "explanation": "",
        "counterparty_count": 4,
        "counterparty_concentration": 0.25,
    }
    values.update(overrides)
    return WhaleSignal(**values)


def test_high_quality_signal_can_be_actionable():
    engine = WhaleSignalEngineV2(DummySource(), DummyMarket())
    signal = engine._enrich_signal(make_signal())
    assert engine._classify_signal(signal) == "actionable"
    assert signal.quality_tier == "actionable"
    assert signal.estimated_notional_usd == 100_000.0


def test_centralized_counterparty_stays_context():
    engine = WhaleSignalEngineV2(DummySource(), DummyMarket())
    signal = engine._enrich_signal(
        make_signal(counterparty_count=1, counterparty_concentration=0.9)
    )
    assert engine._classify_signal(signal) == "context"
    assert engine._is_hub_concentrated(signal)


def test_watchlist_bonus_is_separate_from_discovery_score():
    engine = WhaleSignalEngineV2(DummySource(), DummyMarket())
    signal = engine._enrich_signal(make_signal(token_symbol="ONDO"))
    assert signal.portfolio_bonus == 4.0
    assert signal.token_relevance_score == signal.discovery_score + 4.0


def test_watchlist_without_market_identity_is_not_actionable():
    class MissingMarket:
        source_status = {}

        def get_market_context(self, contract):
            return MarketContext(available=False, limitation="missing")

    engine = WhaleSignalEngineV2(DummySource(), MissingMarket())
    signal = engine._enrich_signal(make_signal(token_symbol="ONDO"))
    assert engine._classify_signal(signal) == "context"
