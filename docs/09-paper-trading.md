# 9. Paper Trading

Le Paper Trading prolonge le backtest par une simulation **continue**, avec un
portefeuille virtuel persistant. Aucun ordre n'est envoyé : ni à Binance, ni au
Testnet. Le Testnet ne sert qu'à lire des bougies publiques.

## Différences avec le backtest

| Point | Backtest | Paper Trading |
|---|---|---|
| Déroulement | boucle sur un historique fini | un cycle par nouvelle bougie clôturée |
| Prix d'exécution d'un signal | ouverture de la bougie suivante | clôture de la bougie qui a produit le signal |
| Stop-loss sur la bougie d'entrée | évalué (le plus bas survient après l'ouverture) | **non évalué** (le plus bas peut précéder l'achat) |
| État | en mémoire, perdu à la fin | SQLite, repris après redémarrage |
| Fin de période | position liquidée `end_of_data` | aucune liquidation artificielle |
| Rejeu | reproductible à volonté | une bougie n'est traitée qu'une fois |

Le changement de prix d'exécution est volontaire : en direct, au moment où la
bougie se clôt, le prix observable est sa clôture ; l'ouverture suivante n'existe
pas encore. Dans un backtest, exécuter à la clôture reviendrait à réutiliser comme
prix d'exécution le prix qui vient de produire le signal — d'où l'ouverture
suivante côté backtest. Les deux conventions sont donc non anticipatives, mais
elles ne sont pas numériquement identiques.

## Modules

| Module | Rôle |
|---|---|
| `tradebot.portfolio.virtual_portfolio` | trésorerie, position, frais, PnL réalisé/latent, drawdown |
| `tradebot.paper.broker` | exécution simulée : slippage, frais, stop-loss |
| `tradebot.paper.engine` | cycle complet : données → signal → risque → exécution → persistance |
| `tradebot.paper.report` | statut, historique, résumé de cycle |
| `tradebot.storage.sqlite_store` | persistance transactionnelle de l'état |
| `tradebot.exchange.market` | bougies publiques clôturées, retries, timeout |
| `tradebot.safety` | garde-fous anti-exécution réelle |

## Comptabilité du portefeuille

- `cash` : trésorerie disponible, jamais négative ;
- `position` : `quantité`, `prix d'entrée` (slippage inclus), horodatage, frais d'achat ;
- `realized_pnl` : somme des PnL nets des transactions clôturées ;
- `unrealized_pnl(prix)` : `quantité × prix − (notionnel d'entrée + frais d'achat)`,
  donc net des frais d'achat et **brut** des frais de sortie ;
- `equity(prix)` : `cash + quantité × prix` ;
- `drawdown` : écart courant au plus haut d'equity.

Invariants vérifiés avant chaque cycle (`VirtualPortfolio.assert_consistent`) :

```
cash = capital initial + realized_pnl − coût de la position ouverte
equity = capital initial + realized_pnl + unrealized_pnl
```

Un état incohérent (base modifiée à la main, interruption douteuse) lève
`PortfolioStateError` : **aucune transaction** n'est effectuée et l'exécution
continue s'arrête en état `error`.

## Frais, slippage, prix d'exécution

| Opération | Prix | Frais |
|---|---|---|
| Achat sur signal | `clôture × (1 + SLIPPAGE_PCT)` | `notionnel × FEE_RATE` |
| Vente sur signal | `clôture × (1 − SLIPPAGE_PCT)` | `notionnel × FEE_RATE` |
| Stop-loss sans gap | `niveau_stop × (1 − SLIPPAGE_PCT)` | idem |
| Stop-loss avec gap | `ouverture × (1 − SLIPPAGE_PCT)` | idem |

Le niveau de stop vaut `prix d'entrée × (1 − STOP_LOSS_PCT)`. Si un stop et un
signal de vente concernent la même bougie, **le stop est prioritaire** : c'est
l'hypothèse la plus défavorable.

## Priorités de risque

1. **Stop-loss** : protection du capital, toujours prioritaire.
2. **Signal de vente** MM10/MM30.
3. **Limite de perte journalière** : elle **bloque les nouvelles entrées** jusqu'au
   prochain jour UTC. Elle ne ferme **pas** la position par défaut ; la fermeture
   n'a lieu que si `CLOSE_POSITION_ON_DAILY_LOSS=true`.
4. **Entrée** : seulement sans position ouverte, sans blocage journalier, avec un
   portefeuille cohérent et un capital suffisant.

Dimensionnement : `budget = min(equity × MAX_POSITION_FRACTION, cash)`, puis
`quantité = budget / (prix × (1 + FEE_RATE))`. Le budget inclut donc les frais, ce
qui interdit un achat qui rendrait la trésorerie négative. Sous 1 USDT de
notionnel, l'entrée est refusée (frais non pertinents).

La perte journalière est mesurée sur l'**equity** et référencée à l'equity à
l'ouverture de la première bougie du jour UTC. La date de référence et l'equity de
référence sont persistées : un redémarrage dans la même journée UTC ne réarme pas
la limite, et un changement de jour UTC la réarme automatiquement.

## Bougies

- Seules les bougies **clôturées** sont exposées : `timestamp + durée_timeframe <= maintenant`.
- Les bougies sont validées (chronologie stricte, prix finis positifs, cohérence OHLC).
  Une donnée invalide produit une erreur, jamais une transaction.
- Au premier démarrage, seule la dernière bougie clôturée est traitée.
- Après une interruption, les bougies manquées sont traitées dans l'ordre, dans la
  limite de `CATCHUP_MAX_CANDLES`.
- Le nombre de bougies demandées couvre la fenêtre longue des moyennes plus la
  profondeur de rattrapage (plafonné à 1 000).

## Persistance SQLite

Fichier : `PAPER_DB_PATH` (défaut `data/paper_state.sqlite3`, ignoré par Git).

| Table | Contenu | Unicité |
|---|---|---|
| `bot_state` | capital, trésorerie, PnL réalisé, pic, référence journalière, statut, drapeau d'arrêt | 1 ligne |
| `positions` | position ouverte | 1 ligne |
| `trades` | transactions clôturées | `(symbole, entrée, sortie)` |
| `decisions` | une décision par bougie | `(symbole, bougie)` |
| `processed_candles` | bougies déjà traitées | `(symbole, timeframe, bougie)` |
| `equity_history` | equity à chaque bougie | `(symbole, bougie)` |

Un cycle est écrit dans **une seule transaction** (`BEGIN IMMEDIATE` …
`COMMIT`), avec `PRAGMA synchronous=FULL` : décision, transaction, état, position et
marqueur de bougie sont validés ensemble ou pas du tout. Un doublon de bougie ou de
transaction annule tout le cycle (`DuplicateCandleError`, `StorageError`).

Le schéma est versionné (`PRAGMA user_version`) : une base écrite par une version
plus récente est refusée plutôt que lue à moitié.

## Exécution ponctuelle et continue

```bash
python -m tradebot.cli paper start --once     # un cycle
python -m tradebot.cli paper start            # boucle, POLL_SECONDS entre deux cycles
```

En continu :

- une erreur réseau ou un délai d'attente est journalisé, le cycle est ignoré et
  retenté au suivant — aucune transaction n'est inventée ;
- `paper stop` pose un drapeau dans SQLite, lu entre deux cycles : sortie propre,
  statut `stopped` ;
- `Ctrl+C` provoque le même arrêt propre ;
- une incohérence de portefeuille ou une erreur de stockage arrête le bot en statut
  `error`.

## Limites connues

- Une seule position à la fois, aucun ordre limite, aucun short.
- Les frais et le slippage sont des hypothèses fixes, pas des mesures de carnet d'ordres.
- Aucune reconnexion WebSocket : la lecture est périodique (REST).
- Aucune démonstration de rentabilité : le Paper Trading valide la **mécanique**
  (exécution, risque, persistance), pas la performance de la stratégie.
- Le passage à un compte testnet avec ordres fictifs reste une étape ultérieure et
  n'est pas implémenté.
