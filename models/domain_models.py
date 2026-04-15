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
class MarketContext:
    token_name: str | None = None
    token_symbol: str | None = None
    market_cap_rank: int | None = None
    current_price_usd: float | None = None
    volume_24h_usd: float | None = None
    price_change_24h: float | None = None
    categories: list[str] | None = None
    market_profile: str = "unknown"
    available: bool = False
    limitation: str | None = None


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
    directional_score: float
    transfer_strength_score: float
    confidence: str
    explanation: str
    is_stablecoin: bool = False
    market_context: MarketContext | None = None


@dataclass
class ScanDiagnostics:
    sampled_logs: int
    focus_term: str | None = None
    source_limitations: list[str] = field(default_factory=list)
