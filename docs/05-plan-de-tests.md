# 5. Plan de tests

## Étape 1 : tests simples
Vérifier à la main que `calculer_signal` donne le bon résultat sur de petits exemples (prix qui montent, qui descendent, plats).

## Étape 2 : backtest
Faire tourner la stratégie sur des données passées (1 à 2 ans de bougies d'1 heure), sans passer de vrais ordres.

À mesurer :
- Rendement total
- Nombre de trades
- Pourcentage de trades gagnants
- Perte maximale en cours de route (drawdown)
- Comparaison avec le simple fait d'acheter et garder (« buy and hold »)

À surveiller : si les résultats ne battent pas le buy and hold, la stratégie n'apporte rien. Il faut aussi tenir compte des frais de l'exchange.

## Étape 3 : simulation sur testnet (paper trading)
Le bot tourne en temps réel avec de l'argent fictif pendant **au moins 2 à 4 semaines**. On vérifie :
- Pas de plantage ni de coupure réseau mal gérée
- Les ordres sont bien exécutés
- Le journal est complet
- Les résultats restent proches du backtest

## Étape 4 : décision
Passage à l'argent réel seulement si toutes les étapes sont concluantes. Si oui : très petite somme, surveillance quotidienne, mêmes règles de risque.
