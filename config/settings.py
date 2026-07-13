import os


# Central settings module so constants do not spread across the codebase.
ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DECIMALS_METHOD = "0x313ce567"
SYMBOL_METHOD = "0x95d89b41"
NAME_METHOD = "0x06fdde03"

SIGNAL_ENGINE_VERSION = "2.0.0"
OPENCLAW_SCHEMA_VERSION = "whalebot.openclaw.v1"

SCAN_LOOKBACK_BLOCKS = 900
SCAN_WINDOW_SECONDS = 3 * 60 * 60
MARKET_LOG_PAGES = 2
MARKET_LOG_PAGE_SIZE = 1000
MIN_CLUSTER_WALLETS = 5
MIN_TOKEN_EVENTS = 4
MAX_METADATA_TOKENS = 35
LARGE_EVENT_PERCENTILE = 0.8
MAX_RESULTS = 3
COINGECKO_ENRICH_LIMIT = 18

# Signal-quality v2: raw token units are not comparable between tokens.
# Actionability therefore depends on market-backed USD notional, direction quality,
# independent counterparties and a discovery score that excludes portfolio bias.
MIN_ESTIMATED_NOTIONAL_USD = 50_000.0
MIN_CONFIRMED_SCORE = 24.0
MAX_COUNTERPARTY_CONCENTRATION = 0.60
MAX_HUB_COUNTERPARTIES = 2

# Shared contract-context cache. Successes stay fresh for a few minutes;
# negative/error results expire quickly so a temporary API problem cannot poison a process.
MARKET_CONTEXT_CACHE_TTL_SECONDS = 180
MARKET_CONTEXT_NEGATIVE_CACHE_TTL_SECONDS = 30

# Broad market pages are reused across market, rotation and confluence calls.
# When CoinGecko rate-limits a later request, a recent stale page can keep research
# operational while the response is explicitly marked degraded.
MARKET_PAGE_CACHE_TTL_SECONDS = 180
MARKET_PAGE_STALE_TTL_SECONDS = 15 * 60

STABLECOIN_SYMBOLS = {
    "USDT",
    "USDC",
    "DAI",
    "USDE",
    "USDS",
    "FDUSD",
    "PYUSD",
    "TUSD",
    "RLUSD",
    "USDD",
    "FRAX",
}

BASE_CONTEXT_SYMBOLS = {
    "ETH",
    "WETH",
    "BTC",
    "WBTC",
    "LBTC",
    "CBBTC",
    "TBTC",
    "RENBTC",
}

# Tokens that are too misleading/noisy for an "opportunity" card.
# They can still be seen in raw output if needed, but not as actionable alpha.
BLACKLIST_SYMBOLS = {
    "HEX",
}

# Portfolio relevance is kept separate from market discovery quality.
# These symbols may receive a transparent ranking bonus, but the bonus cannot
# establish token identity or promote a weak signal to actionable by itself.
WATCHLIST_SYMBOLS = {
    "ONDO",
    "LINK",
    "GRT",
    "CFG",
    "PLUME",
    "FET",
    "NEAR",
    "PENDLE",
    "ETHFI",
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
