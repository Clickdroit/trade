# 3. Gestion du risque

La gestion du risque compte plus que la stratégie : elle protège le capital.

| Règle | Valeur de départ |
|---|---|
| Capital fictif de départ | 1 000 USDT |
| Part du capital engagée par trade | 10 % maximum |
| Stop-loss (vente automatique si le prix baisse de) | 3 % |
| Perte maximale par jour avant arrêt du bot | 5 % du capital |
| Positions ouvertes en même temps | 1 |

## Règles de sécurité
- Si le bot perd plus que la limite journalière, il **s'arrête** et attend une décision humaine.
- Si l'API ne répond pas, le bot n'ouvre aucune nouvelle position.
- Une commande « arrêt d'urgence » doit exister.
- Passage à l'argent réel : jamais avant la fin du plan de tests, et avec une toute petite somme qu'on peut se permettre de perdre.

## Sécurité des clés API
- Créer des clés avec le droit « trading » uniquement, **sans** droit de retrait
- Les stocker dans `.env`, ignoré par Git
- Ne jamais les partager ni les coller dans un chat
