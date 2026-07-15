from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from config.settings import WHALEBOT_DB_PATH
from models.domain_models import TokenMetadata


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class EvidenceLedger:
    """Append-friendly SQLite evidence store for scans, events and static metadata."""

    def __init__(self, path: str = WHALEBOT_DB_PATH) -> None:
        self.path = path
        self._lock = threading.RLock()
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
        self._initialize()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=30)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA journal_mode=WAL")
        connection.execute("PRAGMA synchronous=NORMAL")
        return connection

    def _initialize(self) -> None:
        with self._lock, self._connect() as connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS checkpoints (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS token_metadata (
                    contract TEXT PRIMARY KEY,
                    symbol TEXT NOT NULL,
                    name TEXT NOT NULL,
                    decimals INTEGER NOT NULL,
                    is_stablecoin INTEGER NOT NULL DEFAULT 0,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS scan_runs (
                    run_id TEXT PRIMARY KEY,
                    mode TEXT NOT NULL,
                    focus TEXT,
                    cache_policy TEXT NOT NULL,
                    verification_passes INTEGER NOT NULL,
                    status TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT,
                    result_json TEXT,
                    error TEXT
                );

                CREATE TABLE IF NOT EXISTS transfer_events (
                    event_key TEXT PRIMARY KEY,
                    run_id TEXT,
                    block_number TEXT,
                    transaction_hash TEXT,
                    log_index TEXT,
                    contract TEXT,
                    from_address TEXT,
                    to_address TEXT,
                    raw_value TEXT,
                    timestamp TEXT,
                    observed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_transfer_contract
                ON transfer_events(contract, observed_at);

                CREATE TABLE IF NOT EXISTS signal_observations (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    symbol TEXT,
                    contract TEXT,
                    direction TEXT,
                    quality_tier TEXT,
                    classification TEXT,
                    discovery_score REAL,
                    estimated_notional_usd REAL,
                    wallet_count INTEGER,
                    event_count INTEGER,
                    time_window TEXT,
                    source_quality TEXT,
                    result_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_signal_contract
                ON signal_observations(contract, observed_at);

                CREATE TABLE IF NOT EXISTS market_universe_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    start_page INTEGER NOT NULL,
                    end_page INTEGER NOT NULL,
                    max_pages INTEGER NOT NULL,
                    coins_scanned INTEGER NOT NULL,
                    result_json TEXT NOT NULL,
                    observed_at TEXT NOT NULL
                );
                """
            )

    def get_checkpoint(self, key: str) -> str | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT value FROM checkpoints WHERE key = ?",
                (key,),
            ).fetchone()
        return str(row["value"]) if row else None

    def get_int_checkpoint(self, key: str) -> int | None:
        value = self.get_checkpoint(key)
        if value is None:
            return None
        try:
            return int(value)
        except ValueError:
            return None

    def set_checkpoint(self, key: str, value: str | int) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO checkpoints(key, value, updated_at)
                VALUES(?, ?, ?)
                ON CONFLICT(key) DO UPDATE SET
                    value = excluded.value,
                    updated_at = excluded.updated_at
                """,
                (key, str(value), _utc_now()),
            )

    def get_token_metadata(
        self,
        contract: str,
        max_age_seconds: int,
    ) -> TokenMetadata | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                """
                SELECT contract, symbol, name, decimals, is_stablecoin, updated_at
                FROM token_metadata
                WHERE contract = ?
                """,
                (contract.lower(),),
            ).fetchone()
        if not row:
            return None
        try:
            updated = datetime.fromisoformat(str(row["updated_at"]))
        except ValueError:
            return None
        if datetime.now(timezone.utc) - updated > timedelta(seconds=max_age_seconds):
            return None
        return TokenMetadata(
            contract=str(row["contract"]),
            symbol=str(row["symbol"]),
            name=str(row["name"]),
            decimals=int(row["decimals"]),
            is_stablecoin=bool(row["is_stablecoin"]),
        )

    def upsert_token_metadata(self, metadata: TokenMetadata) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO token_metadata(
                    contract, symbol, name, decimals, is_stablecoin, updated_at
                )
                VALUES(?, ?, ?, ?, ?, ?)
                ON CONFLICT(contract) DO UPDATE SET
                    symbol = excluded.symbol,
                    name = excluded.name,
                    decimals = excluded.decimals,
                    is_stablecoin = excluded.is_stablecoin,
                    updated_at = excluded.updated_at
                """,
                (
                    metadata.contract.lower(),
                    metadata.symbol,
                    metadata.name,
                    metadata.decimals,
                    int(metadata.is_stablecoin),
                    _utc_now(),
                ),
            )

    def start_run(
        self,
        run_id: str,
        mode: str,
        focus: str | None,
        cache_policy: str,
        verification_passes: int,
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO scan_runs(
                    run_id, mode, focus, cache_policy, verification_passes,
                    status, started_at
                )
                VALUES(?, ?, ?, ?, ?, 'STARTED', ?)
                ON CONFLICT(run_id) DO UPDATE SET
                    mode = excluded.mode,
                    focus = excluded.focus,
                    cache_policy = excluded.cache_policy,
                    verification_passes = excluded.verification_passes,
                    status = 'STARTED',
                    started_at = excluded.started_at,
                    finished_at = NULL,
                    result_json = NULL,
                    error = NULL
                """,
                (
                    run_id,
                    mode,
                    focus,
                    cache_policy,
                    verification_passes,
                    _utc_now(),
                ),
            )

    def finish_run(
        self,
        run_id: str,
        status: str,
        result: dict[str, Any] | None = None,
        error: str | None = None,
    ) -> None:
        serialized = json.dumps(result, ensure_ascii=False, default=str) if result is not None else None
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                UPDATE scan_runs
                SET status = ?, finished_at = ?, result_json = ?, error = ?
                WHERE run_id = ?
                """,
                (status, _utc_now(), serialized, error, run_id),
            )

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._lock, self._connect() as connection:
            row = connection.execute(
                "SELECT * FROM scan_runs WHERE run_id = ?",
                (run_id,),
            ).fetchone()
        if not row:
            return None
        result = dict(row)
        if result.get("result_json"):
            try:
                result["result"] = json.loads(result["result_json"])
            except json.JSONDecodeError:
                result["result"] = None
        result.pop("result_json", None)
        return result

    def record_transfer_logs(self, run_id: str, logs: list[dict]) -> int:
        rows = []
        observed_at = _utc_now()
        for log in logs:
            tx_hash = str(log.get("transactionHash", ""))
            log_index = str(log.get("logIndex", ""))
            if not tx_hash or not log_index:
                continue
            topics = log.get("topics") if isinstance(log.get("topics"), list) else []
            from_address = self._topic_address(topics[1]) if len(topics) > 1 else ""
            to_address = self._topic_address(topics[2]) if len(topics) > 2 else ""
            rows.append(
                (
                    f"{tx_hash}:{log_index}",
                    run_id,
                    str(log.get("blockNumber", "")),
                    tx_hash,
                    log_index,
                    str(log.get("address", "")).lower(),
                    from_address,
                    to_address,
                    str(log.get("data", "")),
                    str(log.get("timeStamp", "")),
                    observed_at,
                )
            )
        if not rows:
            return 0
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT OR IGNORE INTO transfer_events(
                    event_key, run_id, block_number, transaction_hash, log_index,
                    contract, from_address, to_address, raw_value, timestamp, observed_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )
        return len(rows)

    def record_signal_snapshot(
        self,
        run_id: str,
        snapshot: dict[str, Any],
        source_quality: str,
    ) -> None:
        rows = []
        for signal in snapshot.get("signals") or []:
            rows.append(
                (
                    run_id,
                    signal.get("symbol"),
                    signal.get("contract"),
                    signal.get("direction"),
                    signal.get("quality_tier"),
                    signal.get("classification"),
                    signal.get("discovery_score"),
                    signal.get("estimated_notional_usd"),
                    signal.get("wallet_count"),
                    signal.get("event_count"),
                    signal.get("time_window"),
                    source_quality,
                    json.dumps(signal, ensure_ascii=False, default=str),
                    _utc_now(),
                )
            )
        if not rows:
            return
        with self._lock, self._connect() as connection:
            connection.executemany(
                """
                INSERT INTO signal_observations(
                    run_id, symbol, contract, direction, quality_tier, classification,
                    discovery_score, estimated_notional_usd, wallet_count, event_count,
                    time_window, source_quality, result_json, observed_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                rows,
            )

    def record_market_universe(
        self,
        run_id: str,
        start_page: int,
        end_page: int,
        max_pages: int,
        result: dict[str, Any],
    ) -> None:
        with self._lock, self._connect() as connection:
            connection.execute(
                """
                INSERT INTO market_universe_snapshots(
                    run_id, start_page, end_page, max_pages,
                    coins_scanned, result_json, observed_at
                )
                VALUES(?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    start_page,
                    end_page,
                    max_pages,
                    int(result.get("coverage", {}).get("coins_scanned", 0)),
                    json.dumps(result, ensure_ascii=False, default=str),
                    _utc_now(),
                ),
            )

    def diagnostics(self) -> dict[str, Any]:
        try:
            with self._lock, self._connect() as connection:
                counts = {
                    "transfer_events": connection.execute(
                        "SELECT COUNT(*) AS n FROM transfer_events"
                    ).fetchone()["n"],
                    "signal_observations": connection.execute(
                        "SELECT COUNT(*) AS n FROM signal_observations"
                    ).fetchone()["n"],
                    "token_metadata": connection.execute(
                        "SELECT COUNT(*) AS n FROM token_metadata"
                    ).fetchone()["n"],
                }
            return {"ok": True, "path": self.path, **counts}
        except sqlite3.Error as exc:
            return {"ok": False, "path": self.path, "error": str(exc)}

    @staticmethod
    def _topic_address(topic: object) -> str:
        text = str(topic or "")
        if text.startswith("0x") and len(text) >= 42:
            return "0x" + text[-40:].lower()
        return ""


_default_ledger: EvidenceLedger | None = None
_default_lock = threading.Lock()


def get_evidence_ledger() -> EvidenceLedger:
    global _default_ledger
    if _default_ledger is None:
        with _default_lock:
            if _default_ledger is None:
                _default_ledger = EvidenceLedger()
    return _default_ledger
