# Trade — Bot de trading crypto éducatif

Bot Python d'apprentissage pour analyser BTC/USDT avec une stratégie de croisement de moyennes mobiles, et **backtester** cette stratégie sur des données historiques.

> **Sécurité :** aucune exécution d'ordre réel n'est implémentée. Aucune clé API n'est nécessaire pour le backtest, qui n'appelle que des données publiques. Le trading comporte un risque de perte.

## État du projet

- [x] Cahier des charges et stratégie initiale
- [x] Architecture Python en modules
- [x] Calcul du croisement MM10/MM30
- [x] Garde-fous de risque de base
- [x] Moteur de backtesting : frais, slippage, stop-loss, limite de perte journalière
- [x] Métriques : rendement, buy & hold, drawdown, Sharpe, win rate, profit factor
- [x] CLI de backtest (CSV local ou téléchargement CCXT)
- [x] Tests automatisés et workflow GitHub Actions
- [ ] Paper trading avec portefeuille virtuel
- [ ] Connexion testnet avec ordres fictifs, après validation
- [ ] Monitoring et arrêt d'urgence

## Installation (Windows PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
```

Sous Linux/macOS : `source .venv/bin/activate`.

## Backtest

Le backtest est **totalement indépendant de l'exécution réelle** : il ne charge que des bougies et ne peut pas envoyer d'ordre.

### Depuis un fichier CSV local

```bash
trade-bot --backtest --csv data/btc_usdt_1h.csv
trade-bot --backtest --csv data/btc_usdt_1h.csv --symbol BTC/USDT --timeframe 1h
trade-bot --backtest --csv data/btc_usdt_1h.csv --start 2024-01-01 --end 2024-03-31
```

Un fichier d'exemple peut être produit une fois pour toutes depuis CCXT (voir ci-dessous), puis réutilisé hors ligne.

### Depuis les données publiques CCXT

```bash
trade-bot --backtest --symbol BTC/USDT --timeframe 1h --days 90
trade-bot --backtest --days 90 --save-csv data/btc_usdt_1h.csv
```

Le téléchargement nécessite un accès réseau aux endpoints publics de Binance (Testnet par défaut) ; aucune clé API n'est utilisée. Selon la disponibilité du Testnet, l'historique peut être limité : `--csv` reste la source la plus reproductible.

### Format du CSV

```csv
timestamp,open,high,low,close,volume
1704067200000,42283.0,42500.0,42100.0,42400.0,120.5
```

- `timestamp` en **millisecondes UTC** ;
- bougies **strictement chronologiques**, sans doublon (un fichier désordonné est refusé) ;
- colonnes obligatoires : `timestamp,open,high,low,close,volume`.

Le dossier `data/` est ignoré par Git : c'est l'emplacement prévu pour vos fichiers historiques locaux.

### Paramètres disponibles

| Option | Rôle | Défaut |
|---|---|---|
| `--symbol` | Paire testée ; en mode CSV, libellé d'affichage | `TRADING_SYMBOL` (`BTC/USDT`) |
| `--timeframe` | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` ; en mode CSV, libellé (aucune conversion) | `TRADING_TIMEFRAME` (`1h`) |
| `--csv` | Source CSV locale | téléchargement CCXT |
| `--save-csv` | Enregistre les données téléchargées | — |
| `--days` | Profondeur téléchargée (CCXT uniquement) | 30 |
| `--start` / `--end` | Période testée (incluse, UTC) | toutes les données |

Les fenêtres de moyennes mobiles, le capital, les frais, le slippage et le stop-loss viennent de `.env` (`SHORT_MA`, `LONG_MA`, `STARTING_BALANCE`, `FEE_RATE`, `SLIPPAGE_PCT`, `STOP_LOSS_PCT`).

### Convention d'exécution (pas de look-ahead)

Un signal calculé sur la clôture de la bougie *N* est exécuté à l'**ouverture de la bougie *N+1***. Les frais sont prélevés à l'achat **et** à la vente, le slippage est toujours défavorable, et un gap sous le stop-loss est exécuté à l'ouverture. Le détail complet est dans [docs/04-architecture.md](docs/04-architecture.md).

## Analyse ponctuelle

```bash
trade-bot --once
```

Cette commande récupère des bougies publiques et affiche un signal. Elle ne passe aucun ordre.

## Tests et lint

```bash
pytest
ruff check .
```

Les tests n'ont besoin ni d'Internet ni de clés API : toutes les données sont synthétiques.

## Configuration et sécurité

Les paramètres sont dans `.env`. Garde `DRY_RUN=true`. Les données publiques ne nécessitent aucune clé API. Ne colle jamais de clé secrète dans le code, les issues ou les conversations. Le backtest ne demande jamais de clé Binance.

## Documentation

- [Cahier des charges](docs/01-cahier-des-charges.md)
- [Stratégie](docs/02-strategie.md)
- [Gestion du risque](docs/03-gestion-risque.md)
- [Architecture](docs/04-architecture.md)
- [Plan de tests](docs/05-plan-de-tests.md)
- [Journal et suivi](docs/06-journal-suivi.md)
- [Planning et risques](docs/07-planning-risques.md)
- [Guide de développement](docs/08-developpement.md)
