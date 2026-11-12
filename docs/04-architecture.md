# Architecture technique

Le projet suit une architecture en couches : domaine, stratégie, gestion du risque, accès exchange, portefeuille virtuel, stockage, backtesting et orchestration. La stratégie et le backtest ne dépendent jamais de Binance.

## Modules

| Module | Rôle |
|---|---|
| `domain` | Signaux, bougies, décisions. Aucune dépendance externe. |
| `strategy` | Indicateurs et règles de croisement. Ne connaît ni l'exchange ni le portefeuille. |
| `risk` | Dimensionnement des positions et limites de perte. |
| `exchange` | Lecture des données publiques du Testnet Binance. Aucun ordre. |
| `portfolio` | Portefeuille virtuel du paper trading (hors backtest). |
| `storage` | Journal CSV des décisions. |
| `backtesting` | Chargement des données, moteur de simulation, métriques. |
| `config` | Paramètres validés, lus depuis l'environnement. |
| `app` | Orchestration d'une analyse ponctuelle (`--once`). |
| `cli` | Point d'entrée `trade-bot` (`--once`, `--loop`, `--backtest`). |

## Flux d'un backtest

1. `backtesting.data_loader` charge des bougies depuis un CSV local ou via CCXT (pagination, tri, dédoublonnage).
2. Le moteur valide les paramètres et les données (ordre chronologique, doublons, prix positifs, cohérence OHLC).
3. Bougie par bougie, il applique le stop-loss, calcule le signal sur les bougies clôturées, exécute à l'ouverture, met à jour la trésorerie et l'equity.
4. La position éventuellement ouverte à la fin est liquidée à la clôture de la dernière bougie.
5. `backtesting.metrics` calcule les métriques et formate le rapport affiché par la CLI.

## Convention temporelle des signaux et exécutions

C'est la règle centrale pour éviter le **biais de look-ahead** :

| Événement | Bougie utilisée | Prix |
|---|---|---|
| Signal d'achat ou de vente | Clôture de la bougie *N* | Non exécutable à ce prix |
| Exécution du signal | Ouverture de la bougie *N+1* | `open × (1 + slippage)` à l'achat, `open × (1 - slippage)` à la vente |
| Stop-loss | Bougies détenues, bougie d'entrée incluse | Niveau de stop, ou ouverture en cas de gap |

Conséquences :

- le prix de clôture qui produit un signal n'est **jamais** utilisé comme prix d'exécution ;
- le premier signal possible exige `long_window + 1` bougies clôturées, donc `long_window + 2` bougies au total ;
- le stop-loss peut être touché dès la bougie d'entrée : le plus bas d'une bougie survient après son ouverture, donc après l'achat ;
- si un stop et un signal de vente concernent la même bougie, le stop est prioritaire (hypothèse la plus défavorable).

## Hypothèses de frais et de slippage

- `fee_rate` (0,1 % par défaut) est prélevé sur le notionnel **à l'achat et à la vente**.
- `pnl_gross = (prix_sortie - prix_entrée) × quantité`.
- `pnl_net = pnl_gross - frais_entrée - frais_sortie`.
- Le slippage (0,05 % par défaut) est appliqué défavorablement à chaque exécution : achat plus cher, vente moins chère.
- Les frais d'achat sont inclus dans le budget : une position dimensionnée à 10 % de l'equity ne peut pas rendre le solde négatif.
- Le **rendement buy & hold** est un simple rendement de prix, du premier `open` au dernier `close`, **hors frais** : il sert de référence, pas de stratégie simulée.

## Gap sous le stop-loss

Deux cas sont distingués :

1. la bougie ouvre **au-dessus** du stop puis le traverse : exécution au niveau du stop, avec slippage ;
2. la bougie ouvre **sous** le stop : exécution à l'ouverture, avec slippage. Le niveau de stop n'était pas disponible sur le marché.

Aucun des deux cas n'utilise un prix meilleur que celui réellement accessible.

## Gestion du risque

- **Taille de position** : `max_position_fraction` (10 % par défaut) de l'equity disponible, frais d'achat inclus.
- **Perte journalière** : mesurée sur l'**equity** (trésorerie + position valorisée au marché), pas sur la trésorerie seule. La référence est l'equity à l'ouverture de la première bougie du jour UTC.
- Une fois la limite atteinte (5 % par défaut), **aucune nouvelle position** n'est ouverte jusqu'au prochain jour UTC. Le stop-loss continue de protéger une position en cours. La limite est réévaluée à l'ouverture et à la clôture de chaque bougie.
- Le solde de trésorerie ne peut jamais devenir négatif ; le moteur lève une erreur explicite si cette invariante est violée.

Avec une position plafonnée à 10 % et un stop à 3 %, la perte maximale théorique d'un trade est d'environ 0,3 % de l'equity, hors gap. La limite journalière de 5 % n'est donc atteinte qu'en cas de gap extrême ou si les paramètres de risque sont assouplis — c'est une propriété du dimensionnement, pas un bug.

## Fin de backtest

Toute position encore ouverte à la dernière bougie est **liquidée à la clôture** de cette bougie, avec slippage et frais. Le motif `end_of_data` est enregistré dans le trade. Sans cette règle, le PnL final dépendrait d'une position non réalisée et les métriques seraient incomparables.

## Données

- CSV : colonnes `timestamp,open,high,low,close,volume`, timestamps en millisecondes, ordre strictement croissant exigé.
- CCXT : pagination par tranches de 1 000 bougies, tri et dédoublonnage, erreurs réseau transformées en `DataLoadError`. La dernière bougie encore en formation est écartée : sa clôture n'est pas définitive.
- En mode `--csv`, `--symbol` et `--timeframe` ne servent que de libellés : le fichier est utilisé tel quel, sans conversion de bougies.
- Le moteur refuse les listes vides ou trop courtes, les doublons, les dates désordonnées et les prix non positifs.

## Ce qui n'existe pas encore

Aucune fonction d'envoi d'ordre n'est incluse. Les modules `portfolio` et `storage` servent au paper trading et au journal, pas à l'exécution réelle. Le passage au testnet avec ordres fictifs reste une étape ultérieure.
