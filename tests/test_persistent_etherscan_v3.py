from unittest.mock import patch

from models.domain_models import TokenMetadata
from services.evidence_ledger import EvidenceLedger
from sources.etherscan_source import EtherscanSource
from sources.persistent_etherscan_source import PersistentEtherscanSource


def test_incremental_range_uses_checkpoint_overlap(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    ledger.set_checkpoint("ethereum:last_completed_block", 10_000)
    source = PersistentEtherscanSource(
        run_id="run-1",
        cache_policy="same_run_reuse",
        ledger=ledger,
    )

    from_block, to_block = source.resolve_scan_range(10_100, default_lookback=900)
    assert from_block == 9_950
    assert to_block == 10_100
    assert source.scan_range["incremental"] is True


def test_audit_refresh_uses_full_lookback(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    ledger.set_checkpoint("ethereum:last_completed_block", 10_000)
    source = PersistentEtherscanSource(
        run_id="run-2",
        cache_policy="audit_refresh",
        ledger=ledger,
    )

    from_block, _ = source.resolve_scan_range(10_100, default_lookback=900)
    assert from_block == 9_200
    assert source.scan_range["incremental"] is False


def test_static_metadata_is_reused_across_source_instances(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    metadata = TokenMetadata(
        contract="0xabc",
        symbol="ABC",
        name="ABC Token",
        decimals=18,
    )

    with patch.object(EtherscanSource, "get_token_metadata", return_value=metadata) as mocked:
        first = PersistentEtherscanSource(
            run_id="run-a",
            cache_policy="same_run_reuse",
            ledger=ledger,
        )
        second = PersistentEtherscanSource(
            run_id="run-b",
            cache_policy="same_run_reuse",
            ledger=ledger,
        )
        assert first.get_token_metadata("0xabc") == metadata
        assert second.get_token_metadata("0xabc") == metadata
        assert mocked.call_count == 1
        assert second.metadata_cache_hits == 1
