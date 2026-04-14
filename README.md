# portfolio

Ein einfacher FastAPI-Bot mit HTML-Frontend.

Aktuell kann der Bot:
- normale Textnachrichten einfach beantworten
- Ethereum-Wallet-Adressen erkennen
- ETH-Guthaben ueber Etherscan abfragen
- die letzten Transaktionen kompakt anzeigen
- mit `scan` breit nach Whale-Clustern in aktuellen Ethereum ERC-20 Transfers suchen
- Tokens erst aus den Events entdecken und dann nach Richtung und Zeitfenster gruppieren
- `scan ondo` oder `scan pepe` als Priorisierung ueber dem breiten Scan verstehen
- beim Fokus-Scan nur priorisieren, nicht so tun als ob der ganze Markt nur aus einem Coin besteht

Was bereits echt ist:
- Etherscan Block-, Log- und Proxy-Abfragen
- echte ERC-20 Transfer-Events auf Ethereum
- dynamische Token-Erkennung aus aktuellen Transfer-Logs
- Cluster-Erkennung ueber mehrere grosse Wallets im gleichen Zeitfenster

Was noch Platzhalter oder nur Proxy-Logik ist:
- accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells
- der breite Markt-Scan ist wegen Etherscan-Result-Limits nur eine aktuelle Stichprobe, nicht Vollabdeckung
- SUI und PLUME brauchen noch eigene Chain- oder Explorer-APIs
- fuer echtes Buy/Sell, Liquiditaet und Preis-Kontext braucht der Bot zusaetzlich DEX-/Marktdatenquellen

Wichtige Environment Variable:
- `ETHERSCAN_API_KEY`
