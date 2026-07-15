from pydantic import BaseModel, Field

from config.settings import (
    DEFAULT_CACHE_POLICY,
    MARKET_UNIVERSE_DEFAULT_MAX_PAGES,
    MARKET_UNIVERSE_DEFAULT_PAGES_PER_RUN,
)


class MessageRequest(BaseModel):
    text: str


class OpenClawScanRequest(BaseModel):
    mode: str = "whale"
    focus: str | None = None
    wallet: str | None = None
    cache_policy: str = DEFAULT_CACHE_POLICY
    verification_passes: int = Field(default=1, ge=1, le=3)
    market_pages_per_run: int = Field(
        default=MARKET_UNIVERSE_DEFAULT_PAGES_PER_RUN,
        ge=1,
        le=25,
    )
    market_max_pages: int = Field(
        default=MARKET_UNIVERSE_DEFAULT_MAX_PAGES,
        ge=1,
        le=25,
    )
