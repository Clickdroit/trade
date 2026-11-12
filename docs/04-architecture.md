# Architecture technique

Le projet suit une architecture en couches : domaine, stratégie, gestion du risque, accès exchange, stockage et orchestration. La stratégie ne dépend jamais de Binance.

## Flux de données

1. L'adaptateur exchange récupère les bougies OHLCV.
2. L'application ignore la bougie encore en formation.
3. La stratégie détecte un croisement réel entre les deux dernières clôtures.
4. Le gestionnaire de risque valide la taille et les limites.
5. Le journal enregistre chaque décision.

## Modules

- `domain` : signaux, bougies et décisions.
- `exchange` : récupération des données du Testnet.
- `strategy` : indicateurs et règles de stratégie.
- `risk` : dimensionnement et limites de perte.
- `storage` : journal CSV puis base de données si nécessaire.
- `app.py` : orchestration.
- `tests` : tests unitaires hors réseau.

Aucune fonction d'envoi d'ordre n'est incluse dans cette étape. Les futurs modules `backtesting`, `portfolio` et `execution` seront ajoutés après validation du moteur de stratégie et des garde-fous.
