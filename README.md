# portfolio

Ein einfacher FastAPI-Bot mit HTML-Frontend.

Aktuell kann der Bot:
- normale Textnachrichten einfach beantworten
- Ethereum-Wallet-Adressen erkennen
- ETH-Guthaben ueber Etherscan abfragen
- die letzten Transaktionen kompakt anzeigen
- mit `scan` Whale-Cluster fuer ONDO, ETH, BTC und POL suchen
- grosse Token-Transfers nach Token, Richtung und Zeitfenster gruppieren
- `scan ondo` oder `scan eth` fuer priorisierte Token-Scans verstehen

Was bereits echt ist:
- Etherscan Block- und Log-Abfragen
- echte ERC-20 Transfer-Events auf Ethereum
- Cluster-Erkennung ueber mehrere grosse Wallets im gleichen Zeitfenster

Was noch Platzhalter oder nur Proxy-Logik ist:
- accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells
- SUI und PLUME brauchen noch eigene Chain- oder Explorer-APIs
- weitere Tokens koennen ueber die Token-Konfiguration spaeter leicht ergaenzt werden

Wichtige Environment Variable:
- `ETHERSCAN_API_KEY`
