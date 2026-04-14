# portfolio

Ein einfacher FastAPI-Bot mit HTML-Frontend.

Aktuell kann der Bot:
- normale Textnachrichten einfach beantworten
- Ethereum-Wallet-Adressen erkennen
- ETH-Guthaben ueber Etherscan abfragen
- die letzten Transaktionen kompakt anzeigen
- mit `scan` die letzten Ethereum-Blocks nach grossen ETH-Transfers durchsuchen
- interessante Sender und Empfaenger als Rangliste zurueckgeben

Wichtige Environment Variable:
- `ETHERSCAN_API_KEY`
