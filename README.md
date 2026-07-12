# Whale Signal Bot

Modulare Whale-Signal-Plattform auf FastAPI-Basis. Der Bot ist ein eigenstaendiger
Dienst; OpenClaw kann ihn ueber die maschinenlesbaren Endpunkte verwenden.

## Struktur

- `app.py` – FastAPI-Entrypoint und Middleware
- `routes/` – API-Endpunkte und HTTP-Wiring
- `services/` – Wallet-, Scan-, Rotation-, Qualitaets- und OpenClaw-Logik
- `sources/` – Etherscan, CoinGecko und DexScreener
- `models/` – typisierte API- und Domain-Objekte
- `utils/` – HTTP, Text, Zeitfenster und ABI-Decoding
- `config/` – zentrale Settings, Schwellen und Versionen

## Befehle

- `scan` – breiter Ethereum ERC-20 Whale-Cluster-Scan
- `scan <coin>` – fokussierter Whale-Scan ohne feste Startliste
- `scan gainers` – Preis-/Volumen-Mover
- `scan rotation` – Relative Staerke gegen BTC, ETH und Altmarkt
- `scan rotation <coin>` – fokussierte Rotation
- `0x...` – Ethereum-Wallet-Check

## OpenClaw API

- `GET /health`
- `GET /capabilities`
- `POST /openclaw/scan`

Beispiel:

```json
{
  "mode": "confluence",
  "focus": "ondo"
}
```

Unterstuetzte Modi:

- `whale`
- `market`
- `rotation`
- `confluence`
- `wallet`

Die Antwort enthaelt Schema-/Engine-Version, Source-Status, Cache-Diagnostik,
strukturierte Scan-Daten und den kompatiblen Textoutput.

## Signal Quality v2

Die v2-Engine beseitigt mehrere systematische Fehlerquellen:

- Markt-Kontext hat TTL statt Prozess-Lebenszeit-Cache
- temporaere 404/API-Fehler werden nur kurz negativ gecacht
- Source-Status ist request-lokal und nicht zwischen parallelen Scans vermischt
- rohe Token-Mengen beeinflussen den Score nicht mehr chainuebergreifend
- USD-Notional, Liquiditaet, Richtungsschaerfe und Wallet-Qualitaet werden bewertet
- dominante Einzel-Gegenparteien werden als Router/Bridge/Exchange/Airdrop-Risiko markiert
- Portfolio-Bonus wird separat ausgewiesen und beweist weder Identitaet noch Actionability
- `actionable` verlangt harte Qualitaetsmerkmale; schwache Signale bleiben Context
- OpenClaw erhaelt strukturierte Snapshots statt nur frei formatiertem Text

## Was real ist

- Etherscan Block-, Log-, Proxy- und Wallet-Abfragen
- echte Ethereum ERC-20 Transfer-Events
- dynamische Token-Erkennung aus aktuellen Logs
- Cluster-Erkennung ueber mehrere Wallets im gleichen Zeitfenster
- CoinGecko Markt-Kontext und Relative-Strength-Daten
- DexScreener-Fallback fuer Market Movers

## Grenzen

- Accumulation/Distribution ist transferbasiert, nicht DEX-buy/sell-bestaetigt
- Etherscan liefert eine aktuelle Stichprobe, keine Vollabdeckung
- Entity Labels fuer Exchanges, Router, Bridges und Treasury-Wallets fehlen noch
- SUI und PLUME brauchen eigene Chain-/Explorer-Quellen

## Environment

- `ETHERSCAN_API_KEY`
- optional `COINGECKO_API_KEY` oder `COINGECKO_DEMO_API_KEY`

## Tests

```bash
pip install -r requirements.txt -r requirements-dev.txt
pytest -q
```

## Naechste sinnvolle Upgrades

- DEX swap/buy/sell confirmation
- Exchange/Bridge/Router entity registry
- Smart-money wallet scoring
- Multi-chain source adapters
- alerting / Telegram
