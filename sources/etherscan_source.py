import requests

from config.settings import (
    DECIMALS_METHOD,
    ETHERSCAN_BASE_URL,
    MARKET_LOG_PAGE_SIZE,
    NAME_METHOD,
    SYMBOL_METHOD,
    TRANSFER_TOPIC,
    get_etherscan_api_key,
)
from models.domain_models import TokenMetadata
from utils.decode_utils import decode_abi_string, decode_uint256


class EtherscanSource:
    """Real Ethereum data source. Limited by Etherscan coverage and result caps."""

    def __init__(self) -> None:
        self._metadata_cache: dict[str, TokenMetadata] = {}

    def has_api_key(self) -> bool:
        return bool(get_etherscan_api_key())

    def call(self, params: dict) -> dict:
        response = requests.get(
            ETHERSCAN_BASE_URL,
            params=params,
            timeout=10,
        )
        response.raise_for_status()
        return response.json()

    def get_eth_balance(self, wallet_address: str) -> str:
        api_key = get_etherscan_api_key()
        if not api_key:
            return "Fehler: ETHERSCAN_API_KEY fehlt auf dem Server."

        data = self.call(
            {
                "chainid": "1",
                "module": "account",
                "action": "balance",
                "address": wallet_address,
                "tag": "latest",
                "apikey": api_key,
            }
        )

        if data.get("status") != "1" or "result" not in data:
            message = data.get("message") or "Unbekannter API-Fehler."
            return f"Fehler: {message}"

        balance_wei = int(data["result"])
        balance_eth = balance_wei / 10**18
        return f"{balance_eth:.6f} ETH"

    def get_wallet_transactions(self, wallet_address: str, limit: int = 3) -> list[dict]:
        api_key = get_etherscan_api_key()
        if not api_key:
            return []

        data = self.call(
            {
                "chainid": "1",
                "module": "account",
                "action": "txlist",
                "address": wallet_address,
                "startblock": "0",
                "endblock": "99999999",
                "page": "1",
                "offset": str(limit),
                "sort": "desc",
                "apikey": api_key,
            }
        )

        result = data.get("result")
        return result if isinstance(result, list) else []

    def get_latest_block_number(self) -> int | None:
        api_key = get_etherscan_api_key()
        if not api_key:
            return None

        data = self.call(
            {
                "chainid": "1",
                "module": "proxy",
                "action": "eth_blockNumber",
                "apikey": api_key,
            }
        )

        result = data.get("result")
        if not isinstance(result, str):
            return None
        return int(result, 16)

    def get_market_transfer_logs(self, from_block: int, to_block: int, pages: int) -> list[dict]:
        api_key = get_etherscan_api_key()
        if not api_key:
            return []

        all_logs: list[dict] = []
        seen_keys: set[tuple[str, str]] = set()

        for page in range(1, pages + 1):
            data = self.call(
                {
                    "chainid": "1",
                    "module": "logs",
                    "action": "getLogs",
                    "fromBlock": str(from_block),
                    "toBlock": str(to_block),
                    "topic0": TRANSFER_TOPIC,
                    "page": str(page),
                    "offset": str(MARKET_LOG_PAGE_SIZE),
                    "apikey": api_key,
                }
            )

            result = data.get("result")
            if not isinstance(result, list) or not result:
                break

            for log in result:
                log_key = (str(log.get("transactionHash", "")), str(log.get("logIndex", "")))
                if log_key not in seen_keys:
                    seen_keys.add(log_key)
                    all_logs.append(log)

            if len(result) < MARKET_LOG_PAGE_SIZE:
                break

        return all_logs

    def get_token_metadata(self, contract_address: str) -> TokenMetadata | None:
        contract_address = contract_address.lower()
        if contract_address in self._metadata_cache:
            return self._metadata_cache[contract_address]

        metadata = self._get_token_metadata_from_history(contract_address)
        if metadata is None:
            metadata = self._get_token_metadata_from_calls(contract_address)
        if metadata is not None:
            self._metadata_cache[contract_address] = metadata
        return metadata

    def _get_token_metadata_from_history(self, contract_address: str) -> TokenMetadata | None:
        api_key = get_etherscan_api_key()
        if not api_key:
            return None

        data = self.call(
            {
                "chainid": "1",
                "module": "account",
                "action": "tokentx",
                "contractaddress": contract_address,
                "page": "1",
                "offset": "1",
                "sort": "desc",
                "apikey": api_key,
            }
        )

        result = data.get("result")
        if not isinstance(result, list) or not result:
            return None

        first_item = result[0]
        decimals_text = str(first_item.get("tokenDecimal", ""))
        if not decimals_text.isdigit():
            return None

        symbol = str(first_item.get("tokenSymbol", "")) or contract_address[:8]
        return TokenMetadata(
            contract=contract_address,
            decimals=int(decimals_text),
            symbol=symbol,
            name=str(first_item.get("tokenName", "")) or symbol,
        )

    def _get_token_metadata_from_calls(self, contract_address: str) -> TokenMetadata | None:
        decimals_hex = self._call_contract_method(contract_address, DECIMALS_METHOD)
        symbol_hex = self._call_contract_method(contract_address, SYMBOL_METHOD)
        name_hex = self._call_contract_method(contract_address, NAME_METHOD)

        decimals = decode_uint256(decimals_hex or "")
        symbol = decode_abi_string(symbol_hex or "")
        name = decode_abi_string(name_hex or "")
        if decimals is None:
            return None

        resolved_symbol = symbol or contract_address[:8]
        return TokenMetadata(
            contract=contract_address,
            decimals=decimals,
            symbol=resolved_symbol,
            name=name or resolved_symbol,
        )

    def _call_contract_method(self, contract_address: str, method_signature: str) -> str | None:
        api_key = get_etherscan_api_key()
        if not api_key:
            return None

        data = self.call(
            {
                "chainid": "1",
                "module": "proxy",
                "action": "eth_call",
                "to": contract_address,
                "data": method_signature,
                "tag": "latest",
                "apikey": api_key,
            }
        )
        return data.get("result")
