# 7. Planning et risques du projet

## Planning proposé

| Étape | Contenu | Durée estimée |
|---|---|---|
| 1 | Environnement, compte testnet, clés API | 1 jour |
| 2 | Récupération des prix + moyennes mobiles | 2 jours |
| 3 | Backtest et analyse des résultats | 3 jours |
| 4 | Ordres sur testnet + gestion du risque | 3 jours |
| 5 | Journal et suivi | 1 jour |
| 6 | Simulation en continu | 2 à 4 semaines |
| 7 | Bilan et décision | 1 jour |

## Risques

| Risque | Mesure |
|---|---|
| Perte d'argent réel | Simulation obligatoire avant tout argent réel |
| Clés API volées | Fichier `.env`, droits limités, pas de retrait |
| Bug dans le bot | Limite de perte journalière, arrêt d'urgence |
| Stratégie qui ne marche pas | Backtest honnête, comparaison au buy and hold |
| Panne réseau ou exchange | Pas de nouvelle position si l'API ne répond pas |
