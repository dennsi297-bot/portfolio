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
- OpenClaw-Modus `discovery` – breiter CoinGecko + paralleler DexScreener Early-Move-Scan mit fokussiertem Ethereum-Whale-Fan-out
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
- `universe`
- `discovery`

Die Antwort enthaelt Schema-/Engine-Version, Source-Status, Cache-Diagnostik,
strukturierte Scan-Daten und den kompatiblen Textoutput.

## Discovery Mesh v4

Der Discovery-Pfad ist jetzt ein eigener Sensor-Layer vor der Whale-Bestaetigung:

- CoinGecko wird ueber mehrere Marktseiten statt nur Top-100 gescannt.
- 1h-/24h-/7d-Bewegung wird ausgewertet; DexScreener liefert zusaetzlich 5m/1h/6h/24h.
- DexScreener laeuft parallel und nicht mehr nur als Fallback bei CoinGecko-Ausfall.
- Ethereum-Kandidaten mit Contract erhalten begrenzte fokussierte Whale-Probes.
- Fokussierte Contract-Scans fragen Etherscan direkt fuer diesen Contract ab, statt davon abzuhaengen, ob er im breiten Top-Sample auftaucht.
- Andere Chains bleiben sichtbar, werden aber explizit als `CHAIN_UNSUPPORTED` fuer Whale-Evidence markiert. Das ist nicht dasselbe wie `NONE_FOUND`.
- Discovery + Whale-Evidence wird als getrennte Evidenz gefuehrt; der Bot erstellt weiterhin keine Orders und keine Paper Entries.
- Asynchrone Job-Zustaende werden im Evidence-Ledger persistiert. Nach einem Prozessneustart verschwinden laufende Jobs nicht still, sondern werden als `INTERRUPTED` markiert.
- `/health` meldet, ob der konfigurierte SQLite-Pfad nach `/tmp` zeigt und damit wahrscheinlich ephemer ist.

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
- Whale-Bestaetigung ist aktuell Ethereum-spezifisch; andere Chains brauchen eigene Chain-/Explorer-Adapter

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
