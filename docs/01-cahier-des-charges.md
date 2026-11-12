# 1. Cahier des charges

## Objectif
Créer un programme en Python qui surveille le prix du Bitcoin et passe des ordres d'achat ou de vente automatiquement, selon une règle simple, sans intervention humaine.

## Périmètre de la version 1
- Marché : crypto
- Paire : BTC/USDT (une seule)
- Exchange : Binance, en mode **testnet** (argent fictif)
- Langage : Python
- Stratégie : croisement de deux moyennes mobiles
- Position : achat ou vente au comptant, sans levier

## Ce que le bot fait
1. Récupère les prix à intervalle régulier
2. Calcule les indicateurs
3. Décide : acheter, vendre ou attendre
4. Passe l'ordre sur le testnet
5. Enregistre chaque décision dans un journal

## Ce que le bot ne fait pas (version 1)
- Pas d'argent réel
- Pas de levier, pas de vente à découvert
- Pas de multi-paires
- Pas d'intelligence artificielle

## Contraintes
- Code simple et commenté, lisible niveau BTS
- Les clés API ne sont jamais écrites dans le code ni envoyées sur GitHub
- Le bot doit pouvoir être arrêté à tout moment

## Critères de réussite
- Le bot tourne 7 jours de suite sans planter
- Chaque ordre est bien enregistré dans le journal
- Le backtest et la simulation donnent des résultats cohérents entre eux
