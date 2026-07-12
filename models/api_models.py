from pydantic import BaseModel


class MessageRequest(BaseModel):
    text: str


class OpenClawScanRequest(BaseModel):
    mode: str = "whale"
    focus: str | None = None
    wallet: str | None = None
