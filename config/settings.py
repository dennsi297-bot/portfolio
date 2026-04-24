import os


# Central settings module so constants do not spread across the codebase.
ETHERSCAN_BASE_URL = "https://api.etherscan.io/v2/api"
COINGECKO_BASE_URL = "https://api.coingecko.com/api/v3"
TRANSFER_TOPIC = "0xddf252ad1be2c89b69c2b068fc378daa952ba7f163c4a11628f55a4df523b3ef"
DECIMALS_METHOD = "0x313ce567"
SYMBOL_METHOD = "0x95d89b41"
NAME_METHOD = "0x06fdde03"

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

# Optional priority terms. The scanner remains broad/signal-first, but these
# symbols get a small score bump if they are detected naturally in the sample.
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
