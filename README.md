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
  Externe Datenquellen wie Etherscan und CoinGecko.
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
- CoinGecko Markt-Kontext fuer Preis, Volume, Market-Cap-Rank und Narrative als Enrichment nutzen
- nur die Top 3 Signale ausgeben
- Signale mit starker accumulation und distribution im selben Zeitfenster komplett verwerfen
- nur Cluster mit mindestens 5 grossen Wallets pro Richtung behalten

## Was bereits echt ist

- Etherscan Block-, Log- und Proxy-Abfragen
- echte ERC-20 Transfer-Events auf Ethereum
- dynamische Token-Erkennung aus aktuellen Transfer-Logs
- Cluster-Erkennung ueber mehrere grosse Wallets im gleichen Zeitfenster
- signal-first Scan-Logik statt fester Coin-Startliste
- CoinGecko Markt-Kontext pro erkanntem Token mit Cache im eigenen Source-Modul
- Top-3-Ranking mit Transfer-Staerke plus Markt-Kontext-Enrichment

## Was noch Platzhalter oder nur Proxy-Logik ist

- accumulation/distribution basiert aktuell auf grossen Token-Transfers, nicht auf bestaetigten DEX-Buys oder DEX-Sells
- der breite Markt-Scan ist wegen Etherscan-Result-Limits nur eine aktuelle Stichprobe, nicht Vollabdeckung
- SUI und PLUME brauchen noch eigene Chain- oder Explorer-APIs
- fuer echtes Buy/Sell, Liquiditaet und Preis-Kontext braucht der Bot zusaetzlich DEX-/Marktdatenquellen
- CoinGecko Mapping kann fuer einzelne Contracts fehlen; dann bleibt das Signal bestehen, aber ohne Markt-Kontext

## Wichtige Environment Variable

- `ETHERSCAN_API_KEY`

## TODO naechste Upgrades

- DEX buy/sell detection
- smart money wallet scoring
- multi-chain support
- alerting
- Telegram integration
