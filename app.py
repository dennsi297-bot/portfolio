from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI()

class Message(BaseModel):
    text: str

@app.get("/")
def read_root():
    return {"message": "Bot läuft auf GitHub 🚀"}

@app.post("/message")
def handle_message(msg: Message):
    text = msg.text.lower()

    if "hallo" in text:
        return {"response": "Hey 👋"}
    elif "preis" in text:
        return {"response": "Kommt drauf an 😏"}
    else:
        return {"response": "Noch nicht gelernt 🤖"}
