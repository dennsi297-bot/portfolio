from dataclasses import dataclass, field


@dataclass
class TokenMetadata:
    contract: str
    symbol: str
    name: str
    decimals: int
    is_stablecoin: bool = False


@dataclass
class TokenTransferEvent:
    contract: str
    symbol: str
    name: str
    from_address: str
    to_address: str
    amount: float
    timestamp: int


@dataclass
class WhaleSignal:
    token_symbol: str
    token_name: str
    token_contract: str
    direction: str
    wallet_addresses: list[str]
    wallet_count: int
    repeated_wallets: int
    event_count: int
    total_size: float
    time_window: str
    large_event_threshold: float
    wallet_quality_score: float
    token_relevance_score: float
    confidence: str
    explanation: str
    is_stablecoin: bool = False


@dataclass
class ScanDiagnostics:
    sampled_logs: int
    focus_term: str | None = None
    source_limitations: list[str] = field(default_factory=list)
