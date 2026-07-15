from models.domain_models import TokenMetadata
from services.evidence_ledger import EvidenceLedger


def test_evidence_ledger_persists_checkpoint_metadata_and_run(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    ledger.set_checkpoint("ethereum:last_completed_block", 12345)
    assert ledger.get_int_checkpoint("ethereum:last_completed_block") == 12345

    metadata = TokenMetadata(
        contract="0xabc",
        symbol="ABC",
        name="Alpha Beta Coin",
        decimals=18,
    )
    ledger.upsert_token_metadata(metadata)
    restored = ledger.get_token_metadata("0xabc", max_age_seconds=60)
    assert restored is not None
    assert restored.symbol == "ABC"
    assert restored.decimals == 18

    ledger.start_run(
        "run-1",
        "whale",
        "ondo",
        "fresh_required",
        2,
    )
    ledger.finish_run("run-1", "COMPLETED", result={"ok": True})
    run = ledger.get_run("run-1")
    assert run is not None
    assert run["status"] == "COMPLETED"
    assert run["result"]["ok"] is True


def test_transfer_logs_are_deduplicated(tmp_path):
    ledger = EvidenceLedger(str(tmp_path / "whalebot.db"))
    log = {
        "transactionHash": "0xhash",
        "logIndex": "0x1",
        "blockNumber": "0x10",
        "address": "0xtoken",
        "data": "0x64",
        "timeStamp": "0x20",
        "topics": [
            "0xtopic",
            "0x" + "0" * 24 + "1" * 40,
            "0x" + "0" * 24 + "2" * 40,
        ],
    }
    ledger.record_transfer_logs("run-a", [log, log])
    diagnostics = ledger.diagnostics()
    assert diagnostics["transfer_events"] == 1
