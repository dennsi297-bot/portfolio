from fastapi import APIRouter

from models.api_models import MessageRequest
from services.message_service import MessageService
from services.signal_engine import WhaleSignalEngine
from services.wallet_service import WalletService
from sources.coingecko_source import CoinGeckoSource
from sources.etherscan_source import EtherscanSource


# Router module keeps HTTP wiring separate from scanner logic.
router = APIRouter()

etherscan_source = EtherscanSource()
coingecko_source = CoinGeckoSource()
wallet_service = WalletService(etherscan_source)
signal_engine = WhaleSignalEngine(etherscan_source, coingecko_source)
message_service = MessageService(wallet_service, signal_engine)


@router.get("/")
def read_root():
    return {"message": "Bot laeuft"}


@router.post("/message")
def handle_message(message: MessageRequest):
    return {"response": message_service.handle_message(message.text)}
