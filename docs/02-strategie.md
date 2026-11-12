# 2. Stratégie de trading

## Principe : croisement de moyennes mobiles
Une moyenne mobile (MM) est la moyenne des N derniers prix de clôture. On en utilise deux :
- **MM courte** (ex. 10 périodes) : réagit vite aux changements
- **MM longue** (ex. 30 périodes) : réagit lentement, donne la tendance

## Règles

| Situation | Décision |
|---|---|
| La MM courte passe **au-dessus** de la MM longue | **Acheter** (si pas de position) |
| La MM courte passe **en dessous** de la MM longue | **Vendre** (si position ouverte) |
| Aucun croisement | Attendre |

## Paramètres de départ
- Intervalle des bougies : 1 heure
- MM courte : 10 · MM longue : 30

Ce sont des points de départ. On les testera pendant le backtest, sans chercher à les « truquer » pour obtenir un beau résultat.

## Limites connues
La stratégie marche mieux quand le marché a une tendance claire. Quand le prix oscille sans direction, elle donne de faux signaux et peut enchaîner de petites pertes.
