from __future__ import annotations

import threading
import time

from config.settings import (
    INCREMENTAL_OVERLAP_BLOCKS,
    SCAN_LOOKBACK_BLOCKS,
    TOKEN_METADATA_CACHE_TTL_SECONDS,
)
from models.domain_models import TokenMetadata
from services.evidence_ledger import EvidenceLedger, get_evidence_ledger
from sources.etherscan_source import EtherscanSource


class PersistentEtherscanSource(EtherscanSource):
    """Etherscan source with static metadata memory and evidence checkpoints."""

    _shared_metadata_cache: dict[str, tuple[float, TokenMetadata]] = {}
    _metadata_lock = threading.RLock()

    def __init__(
        self,
        *,
        run_id: str,
        cache_policy: str,
        ledger: EvidenceLedger | None = None,
    ) -> None:
        super().__init__()
        self.run_id = run_id
        self.cache_policy = cache_policy
        self.ledger = ledger or get_evidence_ledger()
        self.metadata_cache_hits = 0
        self.metadata_cache_misses = 0
        self.scan_range: dict[str, int | str | bool] = {}

    def resolve_scan_range(
        self,
        latest_block: int,
        default_lookback: int = SCAN_LOOKBACK_BLOCKS,
    ) -> tuple[int, int]:
        full_from = max(latest_block - default_lookback, 0)
        checkpoint = self.ledger.get_int_checkpoint("ethereum:last_completed_block")

        if self.cache_policy == "audit_refresh" or checkpoint is None:
            from_block = full_from
            incremental = False
        else:
            from_block = max(
                full_from,
                max(checkpoint - INCREMENTAL_OVERLAP_BLOCKS, 0),
            )
            incremental = True

        self.scan_range = {
            "from_block": from_block,
            "to_block": latest_block,
            "checkpoint_before": checkpoint if checkpoint is not None else -1,
            "overlap_blocks": INCREMENTAL_OVERLAP_BLOCKS,
            "incremental": incremental,
            "cache_policy": self.cache_policy,
        }
        return from_block, latest_block

    def complete_scan(self, to_block: int) -> None:
        self.ledger.set_checkpoint("ethereum:last_completed_block", to_block)
        self.scan_range["checkpoint_after"] = to_block

    def get_market_transfer_logs(
        self,
        from_block: int,
        to_block: int,
        pages: int,
    ) -> list[dict]:
        logs = super().get_market_transfer_logs(from_block, to_block, pages)
        self.ledger.record_transfer_logs(self.run_id, logs)
        return logs

    def get_token_metadata(self, contract_address: str) -> TokenMetadata | None:
        key = contract_address.lower()
        now = time.monotonic()

        with self._metadata_lock:
            cached = self._shared_metadata_cache.get(key)
            if cached is not None:
                expires_at, metadata = cached
                if expires_at > now:
                    self.metadata_cache_hits += 1
                    return metadata
                self._shared_metadata_cache.pop(key, None)

        persisted = self.ledger.get_token_metadata(
            key,
            max_age_seconds=TOKEN_METADATA_CACHE_TTL_SECONDS,
        )
        if persisted is not None:
            self.metadata_cache_hits += 1
            with self._metadata_lock:
                self._shared_metadata_cache[key] = (
                    now + TOKEN_METADATA_CACHE_TTL_SECONDS,
                    persisted,
                )
            return persisted

        self.metadata_cache_misses += 1
        metadata = super().get_token_metadata(key)
        if metadata is not None:
            self.ledger.upsert_token_metadata(metadata)
            with self._metadata_lock:
                self._shared_metadata_cache[key] = (
                    time.monotonic() + TOKEN_METADATA_CACHE_TTL_SECONDS,
                    metadata,
                )
        return metadata

    def cache_diagnostics(self) -> dict[str, int | str | bool]:
        return {
            "metadata_hits": self.metadata_cache_hits,
            "metadata_misses": self.metadata_cache_misses,
            "metadata_ttl_seconds": TOKEN_METADATA_CACHE_TTL_SECONDS,
            **self.scan_range,
        }
