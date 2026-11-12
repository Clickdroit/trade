# Trade — Bot de trading crypto éducatif

Bot Python d'apprentissage pour analyser BTC/USDT avec une stratégie de croisement de moyennes mobiles (MM10/MM30), **backtester** cette stratégie et la faire tourner en **Paper Trading** (simulation continue avec portefeuille virtuel).

> **Sécurité :** aucune exécution d'ordre réel n'est implémentée, aucun retrait n'est possible et aucune clé API n'est nécessaire. Le Paper Trading est entièrement virtuel. Le trading comporte un risque de perte.
>
> **Rentabilité :** ce projet **ne démontre pas** la rentabilité de sa stratégie. Les résultats passés (backtest ou paper) ne préjugent rien des résultats futurs.

## État du projet

- [x] Cahier des charges et stratégie initiale
- [x] Architecture Python en modules
- [x] Calcul du croisement MM10/MM30
- [x] Garde-fous de risque (taille de position, stop-loss, limite journalière)
- [x] Moteur de backtesting : frais, slippage, stop-loss, limite de perte journalière
- [x] Métriques : rendement, buy & hold, drawdown, Sharpe, win rate, profit factor
- [x] CLI de backtest (CSV local ou téléchargement CCXT)
- [x] **Paper Trading** : cycle continu, portefeuille virtuel, exécution simulée
- [x] **Persistance SQLite** : état, position, transactions, décisions, bougies traitées
- [x] Tests automatisés et workflow GitHub Actions
- [ ] Connexion testnet avec ordres fictifs, après validation
- [ ] Monitoring et arrêt d'urgence (le `paper stop` couvre le minimum)

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

## Les quatre modes, à ne pas confondre

| Mode | Fonds réels | Ordres envoyés | Source des prix | Où c'est dans le projet |
|---|---|---|---|---|
| **Backtesting** | Non | Aucun | CSV historique ou téléchargement CCXT | `tradebot backtest` |
| **Paper Trading** | Non | Aucun (exécution simulée en mémoire + SQLite) | Bougies publiques clôturées | `tradebot paper …` |
| **Binance Testnet** | Non (compte de test) | Possible sur le testnet, **non implémenté ici** | Endpoints publics du Testnet | utilisé uniquement pour les données |
| **Trading réel** | **Oui** | Oui | Binance production | **hors périmètre, interdit par le code** |

Le Paper Trading n'est pas un backtest : il avance bougie par bougie, dans l'ordre du temps, sans connaître l'avenir, et il persiste son état entre deux redémarrages. Il n'est pas non plus du trading testnet : aucun ordre n'est transmis, même fictivement, à Binance.

## Paper Trading

Le bot simule un portefeuille virtuel de 1 000 USDT : il récupère les bougies publiques, ignore la bougie en cours, calcule le signal sur la dernière bougie **clôturée**, applique les règles de risque, simule l'achat ou la vente (frais + slippage) et enregistre chaque décision dans SQLite.

```bash
python -m tradebot.cli paper start            # exécution continue
python -m tradebot.cli paper start --once     # un seul cycle
python -m tradebot.cli paper status
python -m tradebot.cli paper stop
python -m tradebot.cli paper history --limit 20
python -m tradebot.cli paper reset            # confirmation interactive obligatoire
```

`trade-bot paper …` fonctionne de la même façon si le paquet est installé.

### Ce que fait un cycle

1. charger l'état sauvegardé (portefeuille, position, référence journalière) ;
2. vérifier que la source de données répond et récupérer les bougies ;
3. **exclure les bougies non clôturées** ;
4. ne traiter que les bougies jamais vues (dans l'ordre chromatologique), au maximum `CATCHUP_MAX_CANDLES` par cycle ;
5. changer de journée UTC si nécessaire et réévaluer la limite de perte journalière ;
6. appliquer le stop-loss, puis le signal MM10/MM30 ;
7. simuler l'opération autorisée, avec frais et slippage ;
8. enregistrer atomiquement bougie traitée + décision + transaction + état ;
9. afficher un résumé du portefeuille.

Au tout premier démarrage, seule la dernière bougie clôturée est traitée : l'historique sert uniquement au calcul des moyennes mobiles.

### Commande `status`

Affiche le capital initial, le solde disponible, la valeur totale, le PnL réalisé, le PnL latent, la position en cours, le nombre de transactions, le drawdown, la limite journalière et l'état du bot. Aucun accès réseau n'est nécessaire.

### Arrêt et redémarrage

`paper stop` écrit un drapeau lu entre deux cycles par une exécution continue : la sortie est propre et l'état reste cohérent. Un redémarrage reprend le portefeuille, la position et la référence de perte journalière ; une bougie déjà traitée n'est jamais retraitée.

### Réinitialisation

`paper reset` demande une confirmation explicite (`oui`). Sans confirmation, rien n'est supprimé. `--yes` existe pour les scripts, jamais par défaut.

### Prix d'exécution

- Décision prise à la **clôture** de la bougie traitée ; achat à `clôture × (1 + slippage)`, vente à `clôture × (1 − slippage)`.
- Stop-loss : `min(ouverture, niveau de stop)` puis slippage défavorable ; un gap sous le stop est exécuté à l'ouverture.
- Frais prélevés sur le notionnel à l'achat **et** à la vente.
- Le stop n'est jamais évalué sur la bougie d'entrée (son plus bas peut précéder l'achat).
- Détails et différences avec le backtest : [docs/09-paper-trading.md](docs/09-paper-trading.md).

## Backtest

Le backtest est **totalement indépendant de l'exécution** : il ne charge que des bougies et ne peut pas envoyer d'ordre.

### Depuis un fichier CSV local

```bash
python -m tradebot.cli backtest --csv data/btc_usdt_1h.csv
python -m tradebot.cli backtest --csv data/btc_usdt_1h.csv --symbol BTC/USDT --timeframe 1h
python -m tradebot.cli backtest --csv data/btc_usdt_1h.csv --start 2024-01-01 --end 2024-03-31
```

La forme historique `trade-bot --backtest --csv …` reste supportée.

### Depuis les données publiques CCXT

```bash
python -m tradebot.cli backtest --symbol BTC/USDT --timeframe 1h --days 90
python -m tradebot.cli backtest --days 90 --save-csv data/btc_usdt_1h.csv
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

Le dossier `data/` est ignoré par Git : c'est l'emplacement des fichiers historiques locaux et de la base SQLite du Paper Trading.

### Paramètres disponibles

| Option | Rôle | Défaut |
|---|---|---|
| `--symbol` | Paire testée ; en mode CSV, libellé d'affichage | `TRADING_SYMBOL` (`BTC/USDT`) |
| `--timeframe` | `1m`, `5m`, `15m`, `1h`, `4h`, `1d` ; en mode CSV, libellé (aucune conversion) | `TRADING_TIMEFRAME` (`1h`) |
| `--csv` | Source CSV locale | téléchargement CCXT |
| `--save-csv` | Enregistre les données téléchargées | — |
| `--days` | Profondeur téléchargée (CCXT uniquement) | 30 |
| `--start` / `--end` | Période testée (incluse, UTC) | toutes les données |

Les fenêtres de moyennes mobiles, le capital, les frais, le slippage et le stop-loss viennent de `.env` (`SHORT_MA`, `LONG_MA`, `STARTING_BALANCE`, `FEE_RATE`, `SLIPPAGE_PCT`, `STOP_LOSS_PCT`, `MAX_POSITION_FRACTION`, `MAX_DAILY_LOSS_FRACTION`).

### Convention d'exécution du backtest (pas de look-ahead)

Un signal calculé sur la clôture de la bougie *N* est exécuté à l'**ouverture de la bougie *N+1***. Les frais sont prélevés à l'achat **et** à la vente, le slippage est toujours défavorable, et un gap sous le stop-loss est exécuté à l'ouverture. Le détail complet est dans [docs/04-architecture.md](docs/04-architecture.md).

## Règles de gestion des risques

| Règle | Valeur par défaut |
|---|---|
| Capital fictif | 1 000 USDT |
| Part de l'equity par position | 10 % (`MAX_POSITION_FRACTION`) |
| Stop-loss | 3 % sous le prix d'entrée (`STOP_LOSS_PCT`) |
| Perte journalière maximale | 5 % de l'equity (`MAX_DAILY_LOSS_FRACTION`) |
| Positions simultanées | 1 |
| Notionnel minimal d'une entrée | 1 USDT |

**Priorités de sortie** : 1) stop-loss, 2) signal de vente, 3) sortie sur limite journalière **uniquement** si `CLOSE_POSITION_ON_DAILY_LOSS=true`. Par défaut, la limite journalière **bloque les entrées** mais ne ferme pas la position : le stop-loss continue de la protéger.

Une entrée est refusée si une position est déjà ouverte, si la limite journalière est atteinte, si les données sont invalides, si le portefeuille est incohérent ou si le capital disponible est insuffisant. Détail : [docs/03-gestion-risque.md](docs/03-gestion-risque.md).

## Analyse ponctuelle

```bash
python -m tradebot.cli --once
```

Cette commande récupère des bougies publiques et affiche un signal. Elle ne passe aucun ordre et n'écrit pas dans la base du Paper Trading.

## Tests et lint

```bash
pytest
ruff check .
```

Les tests n'ont besoin ni d'Internet ni de clés API : toutes les données sont synthétiques, aucune horloge réelle n'est utilisée pour les journées UTC, et la source de marché est remplacée par un double de test.

## Configuration et sécurité

Les paramètres sont dans `.env` (voir `.env.example`). Garde `DRY_RUN=true` et `EXECUTION_MODE=paper` : le code **refuse de démarrer** dans tout autre mode. Les données publiques ne nécessitent aucune clé API. Ne colle jamais de clé secrète dans le code, les issues ou les conversations.

Protections en place :

- aucun endpoint d'ordre ni de retrait dans le dépôt ;
- client CCXT toujours en sandbox, sans clé API ; un client authentifié est refusé ;
- mode d'exécution validé (`paper` uniquement) et `DRY_RUN=false` rejeté ;
- état du portefeuille vérifié avant chaque cycle (aucune transaction si incohérent) ;
- données invalides ou incomplètes → aucune opération.

## Documentation

- [Cahier des charges](docs/01-cahier-des-charges.md)
- [Stratégie](docs/02-strategie.md)
- [Gestion du risque](docs/03-gestion-risque.md)
- [Architecture](docs/04-architecture.md)
- [Plan de tests](docs/05-plan-de-tests.md)
- [Journal et suivi](docs/06-journal-suivi.md)
- [Planning et risques](docs/07-planning-risques.md)
- [Guide de développement](docs/08-developpement.md)
- [Paper Trading](docs/09-paper-trading.md)
