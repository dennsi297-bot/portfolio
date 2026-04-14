from fastapi import FastAPI
from pydantic import BaseModel
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI()

# 👉 CORS FIX (wichtig!)
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

class Message(BaseModel):
    text: str

@app.get("/")
def read_root():
    return {"message": "Bot läuft 🚀"}

@app.post("/message")
def handle_message(msg: Message):
    text = msg.text.lower()

    if "hallo" in text:
        return {"response": "Hey 👋"}
    elif "preis" in text:
        return {"response": "Kommt drauf an 😏"}
    else:
        return {"response": "Noch nicht gelernt 🤖"}
