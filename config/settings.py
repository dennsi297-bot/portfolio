import os


# Central settings module so constants do not spread across the codebase.
ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DECIMALS_METHOD = "0x313ce567"
SYMBOL_METHOD = "0x95d89b41"
NAME_METHOD = "0x06fdde03"

SIGNAL_ENGINE_VERSION = "3.0.0"
OPENCLAW_SCHEMA_VERSION = "whalebot.openclaw.v1"
QUALITY_ARCHITECTURE_VERSION = "whalebot.quality.v3"

SCAN_LOOKBACK_BLOCKS = 900
INCREMENTAL_OVERLAP_BLOCKS = 50
SCAN_WINDOW_SECONDS = 3 * 60 * 60
MARKET_LOG_PAGES = 2
MARKET_LOG_PAGE_SIZE = 1000
MIN_CLUSTER_WALLETS = 5
MIN_TOKEN_EVENTS = 4
MAX_METADATA_TOKENS = 35
METADATA_RESOLUTION_WORKERS = 3
LARGE_EVENT_PERCENTILE = 0.8
MAX_RESULTS = 3
COINGECKO_ENRICH_LIMIT = 18

# Signal-quality rules: raw token units are not comparable between tokens.
MIN_ESTIMATED_NOTIONAL_USD = 50_000.0
MIN_CONFIRMED_SCORE = 24.0
MAX_COUNTERPARTY_CONCENTRATION = 0.60
MAX_HUB_COUNTERPARTIES = 2

# Static token identity is safe to retain much longer than dynamic market data.
TOKEN_METADATA_CACHE_TTL_SECONDS = 7 * 24 * 60 * 60

# Dynamic contract context stays short-lived.
MARKET_CONTEXT_CACHE_TTL_SECONDS = 180
MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS = 30

# Broad market pages are reused only when the caller permits same-run reuse.
# A recent stale page may keep research visible, but it is always marked degraded
# and can never create a new actionable/strong-confluence decision.
MARKET_PAGE_CACHE_TTL_SECONDS = 180
MARKET_PAGE_STALE_TTL_SECONDS = 15 * 60
COINGECKO_CIRCUIT_BREAKER_SECONDS = 90

CACHE_POLICIES = {"same_run_reuse", "fresh_required", "audit_refresh"}
DEFAULT_CACHE_POLICY = "same_run_reuse"

# Long scans are serialized by default to protect evidence quality and API quotas.
SCAN_JOB_MAX_WORKERS = int(os.getenv("WHALEBOT_SCAN_JOB_MAX_WORKERS", "1"))
SCAN_JOB_RETENTION_SECONDS = 6 * 60 * 60

# SQLite evidence ledger. On Render, point WHALEBOT_DB_PATH at a persistent disk
# to preserve evidence and checkpoints across service restarts.
WHALEBOT_DB_PATH = os.getenv("WHALEBOT_DB_PATH", "/tmp/whalebot/whalebot.db")

# Rolling broad-market coverage.
MARKET_UNIVERSE_DEFAULT_PAGES_PER_RUN = 3
MARKET_UNIVERSE_DEFAULT_MAX_PAGES = 25
MARKET_UNIVERSE_MAX_PAGES_PER_REQUEST = 25

STABLECOIN_SYMBOLS = {
    "USDT", "USDC", "DAI", "USDE", "USDS", "FDUSD", "PYUSD",
    "TUSD", "RLUSD", "USDD", "FRAX",
}

BASE_CONTEXT_SYMBOLS = {
    "ETH", "WETH", "BTC", "WBTC", "LBTC", "CBBTC", "TBTC", "RENBTC",
}

BLACKLIST_SYMBOLS = {"HEX"}

WATCHLIST_SYMBOLS = {
    "ONDO", "LINK", "GRT", "CFG", "PLUME", "FET", "NEAR", "PENDLE", "ETHFI",
}

DEPRIORITIZED_MAJOR_SYMBOLS = BASE_CONTEXT_SYMBOLS | STABLECOIN_SYMBOLS
UNSUPPORTED_SCAN_TERMS = {
    "sui": "SUI braucht eine eigene Sui-Datenquelle. Der aktuelle breite Scan deckt nur Ethereum ERC-20 Aktivitaet ab.",
    "plume": "PLUME braucht eine eigene Plume- oder EVM-Datenquelle. Der aktuelle breite Scan deckt nur Ethereum ERC-20 Aktivitaet ab.",
    "market": None,
}


def get_etherscan_api_key() -> str | None:
    return os.getenv("ETHERSCAN_API_KEY")


def get_coingecko_api_key() -> str | None:
    return os.getenv("COINGECKO_API_KEY") or os.getenv("COINGECKO_DEMO_API_KEY")
