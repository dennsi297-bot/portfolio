from unittest.mock import patch

from services.discovery_mesh import DiscoveryMeshService
from services.evidence_ledger import EvidenceLedger
from services.openclaw_service import OpenClawService
from services.signal_engine_v3 import WhaleSignalEngineV3
from sources.persistent_etherscan_source import PersistentEtherscanSource


class FakeDiscoverySource:
    def __init__(self):
        self.dex_calls = 0

    def get_market_page(self, page: int = 1, per_page: int = 100):
        if page > 2:
            return []
        return [
            {
                "id": f"coin-{page}",
                "name": f"Coin {page}",
                "symbol": f"C{page}",
                "price": 1.0,
                "change_1h": 8.0 + page,
                "change_24h": 12.0 + page,
                "change_7d": 15.0,
                "volume_24h": 5_000_000,
                "market_cap": 25_000_000,
                "rank": page,
                "source": "CoinGecko",
            }
        ]

    def get_dexscreener_discovery(self, limit: int = 40):
        self.dex_calls += 1
        return [
            {
                "name": "Ethereum Runner",
                "symbol": "RUN",
                "price": 0.1,
                "change_5m": 4.0,
                "change_1h": 18.0,
                "change_6h": 28.0,
                "change_24h": 40.0,
                "change_7d": None,
                "volume_24h": 8_000_000,
                "liquidity_usd": 1_000_000,
                "market_cap": 20_000_000,
                "rank": None,
                "source": "DexScreener",
                "chain": "ethereum",
                "token_address": "0x" + "1" * 40,
                "pair_url": "https://example.test/pair",
            },
            {
                "name": "Sol Runner",
                "symbol": "SOLRUN",
                "price": 0.1,
                "change_5m": 5.0,
                "change_1h": 20.0,
                "change_6h": 30.0,
                "change_24h": 45.0,
                "change_7d": None,
                "volume_24h": 9_000_000,
                "liquidity_usd": 1_500_000,
                "market_cap": 22_000_000,
                "rank": None,
                "source": "DexScreener",
                "chain": "solana",
                "token_address": "So11111111111111111111111111111111111111112",
                "pair_url": "https://example.test/solpair",
            },
        ]


def test_discovery_mesh_queries_dex_even_when_coingecko_succeeds():
    source = FakeDiscoverySource()
    result = DiscoveryMeshService(source).scan(
        coingecko_pages=2,
        coingecko_per_page=100,
        dex_limit=20,
        top_n=10,
    )

    assert result["ok"] is True
    assert source.dex_calls == 1
    assert result["coverage"]["coingecko_rows"] == 2
    assert result["coverage"]["dexscreener_rows"] == 2

    by_symbol = {row["symbol"]: row for row in result["top_candidates"]}
    assert by_symbol["RUN"]["whale_status"] == "PENDING"
    assert by_symbol["SOLRUN"]["whale_status"] == "CHAIN_UNSUPPORTED"
    assert by_symbol["RUN"]["status"] in {"explosive_acceleration", "accelerating"}


def test_discovery_openclaw_fans_out_only_ethereum_contracts(monkeypatch):
    market_data = {
        "ok": True,
        "mode": "discovery",
        "decision_eligible": False,
        "coverage": {"combined_rows": 2},
        "top_candidates": [
            {
                "symbol": "RUN",
                "chain": "ethereum",
                "token_address": "0x" + "1" * 40,
                "discovery_score": 42.0,
                "whale_status": "PENDING",
            },
            {
                "symbol": "SOLRUN",
                "chain": "solana",
                "token_address": "So111",
                "discovery_score": 50.0,
                "whale_status": "CHAIN_UNSUPPORTED",
            },
        ],
    }

    class FakeMarket:
        source_status = {"CoinGecko": "ok", "DexScreener": "ok"}
        last_errors = []

        def __init__(self, cache_policy="same_run_reuse"):
            self.cache_policy = cache_policy

        def cache_diagnostics(self):
            return {}

    monkeypatch.setattr(
        "services.openclaw_service.FreshCoinGeckoSource",
        FakeMarket,
    )
    monkeypatch.setattr(
        "services.openclaw_service.DiscoveryMeshService.scan",
        lambda self: market_data,
    )

    service = OpenClawService()
    calls = []

    def fake_run_single(mode, focus, wallet, **kwargs):
        calls.append((mode, focus))
        return {
            "ok": True,
            "degraded": False,
            "decision_eligible": True,
            "source_status": {"Etherscan": "ok", "CoinGecko": "ok"},
            "source_errors": [],
            "data": {
                "signals": [
                    {
                        "symbol": "RUN",
                        "contract": focus,
                        "direction": "accumulation",
                        "quality_tier": "confirmed",
                    }
                ]
            },
        }

    monkeypatch.setattr(service, "_run_single", fake_run_single)
    result = service._run_discovery_mesh(
        cache_policy="fresh_required",
        run_id="mesh-test",
    )

    assert calls == [("whale", "0x" + "1" * 40)]
    candidates = {row["symbol"]: row for row in result["data"]["top_candidates"]}
    assert candidates["RUN"]["whale_status"] == "WHALE_FOUND"
    assert candidates["RUN"]["confluence"] == "market_plus_whale"
    assert candidates["SOLRUN"]["whale_status"] == "CHAIN_UNSUPPORTED"


def test_contract_focus_only_accepts_valid_ethereum_contract():
    valid = "0x" + "a" * 40
    assert WhaleSignalEngineV3._contract_focus(valid) == valid
    assert WhaleSignalEngineV3._contract_focus("ondo") is None
    assert WhaleSignalEngineV3._contract_focus("0x123") is None


def test_scan_job_state_is_persisted_and_interrupted_on_restart(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    job = {
        "job_id": "job-1",
        "status": "RUNNING",
        "submitted_at": "2026-09-24T12:00:00+00:00",
        "started_at": "2026-09-24T12:00:01+00:00",
        "finished_at": None,
        "request": {"mode": "discovery"},
        "result": None,
        "error": None,
    }
    ledger.upsert_scan_job(job)
    assert ledger.get_scan_job("job-1")["status"] == "RUNNING"

    changed = ledger.mark_incomplete_jobs_interrupted()
    restored = ledger.get_scan_job("job-1")

    assert changed == 1
    assert restored["status"] == "INTERRUPTED"
    assert "restarted" in restored["error"].lower()


def test_focused_scan_range_does_not_use_broad_incremental_checkpoint(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    ledger.set_checkpoint("ethereum:last_completed_block", 9_950)
    source = PersistentEtherscanSource(
        run_id="focused-range",
        cache_policy="same_run_reuse",
        ledger=ledger,
    )

    from_block, to_block = source.resolve_focused_scan_range(10_000, 900)

    assert (from_block, to_block) == (9_100, 10_000)
    assert source.scan_range["incremental"] is False
    assert source.scan_range["focused"] is True
    assert ledger.get_int_checkpoint("ethereum:last_completed_block") == 9_950


def test_focused_completion_does_not_advance_broad_checkpoint():
    class FakeSource:
        def __init__(self):
            self.completed = []

        def complete_scan(self, to_block):
            self.completed.append(to_block)

    source = FakeSource()
    engine = WhaleSignalEngineV3(source, market_source=object())
    engine._complete_checkpoint(123, focused=True)
    assert source.completed == []
    engine._complete_checkpoint(124, focused=False)
    assert source.completed == [124]
