# 3. Gestion du risque

La gestion du risque compte plus que la stratégie : elle protège le capital.

| Règle | Valeur de départ |
|---|---|
| Capital fictif de départ | 1 000 USDT |
| Part du capital engagée par trade | 10 % maximum |
| Stop-loss (vente automatique si le prix baisse de) | 3 % |
| Perte maximale par jour avant arrêt du bot | 5 % du capital |
| Positions ouvertes en même temps | 1 |
| Notionnel minimal d'une entrée | 1 USDT |

La perte journalière est mesurée sur l'**equity** (trésorerie + position valorisée au marché), pas sur la trésorerie seule, avec une référence prise à l'ouverture de la première bougie du jour UTC. Dans le backtest comme en Paper Trading, la limite atteinte bloque uniquement les nouvelles entrées jusqu'au jour UTC suivant ; le stop-loss continue de protéger la position en cours. Voir [04-architecture.md](04-architecture.md) et [09-paper-trading.md](09-paper-trading.md).

## Priorités et refus

Ordre d'application, du plus prioritaire au moins prioritaire :

1. **stop-loss** : protection du capital ;
2. **signal de vente** MM10/MM30 ;
3. **sortie sur limite journalière** : uniquement si `CLOSE_POSITION_ON_DAILY_LOSS=true` ;
4. **entrée** : seulement sans position ouverte et sans blocage journalier.

Une entrée est refusée si :

- une position est déjà ouverte (pas de positions dupliquées) ;
- la limite de perte journalière est atteinte ;
- les données de marché sont invalides (prix non finis, OHLC incohérent, bougies non chronologiques) ;
- l'état du portefeuille est incohérent (trésorerie ≠ capital initial + PnL réalisé − coût de la position) ;
- la trésorerie ou le budget disponible est insuffisant (y compris sous 1 USDT de notionnel).

Un achat impossible faute de capital est **refusé**, jamais redimensionné au-delà du solde. Le budget inclut les frais d'achat : `budget = min(equity × MAX_POSITION_FRACTION, cash)`, puis `quantité = budget / (prix × (1 + frais))`.

## Règles de sécurité
- Si le bot perd plus que la limite journalière, il **n'ouvre plus de nouvelle position** jusqu'au prochain jour UTC (et n'ouvre pas non plus de position dans le backtest).
- Si l'API ne répond pas, le bot n'ouvre aucune nouvelle position.
- Une commande « arrêt d'urgence » doit exister.
- Passage à l'argent réel : jamais avant la fin du plan de tests, et avec une toute petite somme qu'on peut se permettre de perdre.

## Sécurité des clés API
- Créer des clés avec le droit « trading » uniquement, **sans** droit de retrait
- Les stocker dans `.env`, ignoré par Git
- Ne jamais les partager ni les coller dans un chat
