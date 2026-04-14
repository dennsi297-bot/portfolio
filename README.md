# portfolio

Modulare Whale-Signal-Plattform auf FastAPI-Basis.

## Struktur

- `app.py`
  FastAPI-Entrypoint und Middleware.
- `routes/`
  API-Endpunkte und HTTP-Wiring.
- `services/`
  Business-Logik fuer Wallet-Checks, Scan-Flow und Signal-Engine.
- `sources/`
  Externe Datenquellen wie Etherscan.
- `models/`
  Typisierte API- und Domain-Objekte.
- `utils/`
  Kleine Hilfsfunktionen fuer Text, Zeitfenster und ABI-Decoding.
- `config/`
  Zentrale Settings, Konstanten und Limits.

## Was aktuell funktioniert

- normale Textnachrichten einfach beantworten
- Ethereum-Wallet-Adressen erkennen
- ETH-Guthaben ueber Etherscan abfragen
- die letzten Transaktionen kompakt anzeigen
- mit `scan` breit nach Whale-Clustern in aktuellen Ethereum ERC-20 Transfers suchen
- Tokens erst aus den Events entdecken und dann nach Richtung und Zeitfenster gruppieren
- `scan ondo` oder `scan pepe` als Priorisierung ueber dem breiten Scan verstehen
- Stablecoins im Ranking eher nach hinten schieben
- Wallet-Qualitaet, Wiederholungen und Token-Relevanz in ein einfaches Ranking einbauen

## Was bereits echt ist

- Etherscan Block-, Log- und Proxy-Abfragen
- echte ERC-20 Transfer-Events auf Ethereum
- dynamische Token-Erkennung aus aktuellen Transfer-Logs
- Cluster-Erkennung ueber mehrere grosse Wallets im gleichen Zeitfenster
- signal-first Scan-Logik statt fester Coin-Startliste

## Was noch Platzhalter oder nur Proxy-Logik ist

- accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells
- der breite Markt-Scan ist wegen Etherscan-Result-Limits nur eine aktuelle Stichprobe, nicht Vollabdeckung
- SUI und PLUME brauchen noch eigene Chain- oder Explorer-APIs
- fuer echtes Buy/Sell, Liquiditaet und Preis-Kontext braucht der Bot zusaetzlich DEX-/Marktdatenquellen

## Wichtige Environment Variable

- `ETHERSCAN_API_KEY`

## TODO naechste Upgrades

- DEX buy/sell detection
- smart money wallet scoring
- multi-chain support
- alerting
- Telegram integration
