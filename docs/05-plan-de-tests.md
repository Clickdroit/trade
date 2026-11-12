# 5. Plan de tests

## Principe

Les tests sont **déterministes** : données synthétiques, aucun accès Internet, aucune clé API, aucun appel à Binance. Ils doivent pouvoir tourner en CI et sur une machine hors ligne.

```bash
pytest
ruff check .
```

## Tests automatisés

### Stratégie (`tests/test_strategy.py`)

- moyenne mobile simple et rejet d'une fenêtre invalide ;
- croisement haussier (MM courte passe au-dessus de la longue) ;
- croisement baissier ;
- absence de signal quand les moyennes ne se croisent pas ;
- absence de signal répété sans nouveau croisement ;
- données insuffisantes → `HOLD` ;
- fenêtres invalides → `ValueError`.

### Moteur de backtest (`tests/test_backtest_engine.py`)

- marché plat → aucun trade, rendement nul ;
- trade gagnant, avec entrée à l'ouverture suivant le signal ;
- trade perdant ;
- stop-loss déclenché au niveau du stop, avec slippage ;
- gap sous le stop → exécution à l'ouverture, jamais au niveau du stop ;
- frais prélevés à l'achat et à la vente, PnL brut/net cohérents ;
- frais nuls → PnL net = PnL brut ;
- position encore ouverte en fin de période → liquidation `end_of_data` ;
- plusieurs trades successifs → comptabilité cohérente (`equity finale = capital initial + somme des PnL nets`) ;
- limite de perte journalière atteinte → plus aucune entrée le reste du jour UTC ;
- réinitialisation de la limite au changement de jour UTC ;
- taille de position plafonnée à 10 % ;
- solvabilité conservée sur un gap extrême ;
- données vides, insuffisantes, désordonnées, dupliquées, prix nuls ou OHLC incohérents → `ValueError` ;
- paramètres invalides (fenêtres, capital, frais, slippage, stop, limites) → `ValueError`.

### Métriques (`tests/test_metrics.py`)

- rendement total et rejet d'une valeur de départ nulle ;
- drawdown maximal pic-à-creux, cas limites ;
- ratio de Sharpe : formule d'échantillon, annualisation selon la fréquence, `None` si indéfini ;
- taux de réussite (les trades à PnL nul ne sont pas gagnants) ;
- profit factor, y compris `inf` sans perte et `None` sans trade ;
- gain moyen et perte moyenne ;
- rapport : `n/a` au lieu d'une valeur inventée, profit factor infini affiché explicitement.

### Chargement des données (`tests/test_data_loader.py`)

- aller-retour CSV ;
- fichier absent, colonnes manquantes, ligne invalide, doublons, fichier vide ;
- timeframe, symbole et profondeur invalides rejetés avant tout appel réseau ;
- pagination CCXT simulée : tri et dédoublonnage ;
- bougie non clôturée écartée du téléchargement ;
- erreur réseau transformée en `DataLoadError`.

### CLI (`tests/test_cli.py`)

- `--backtest --csv` affiche le rapport et renvoie 0 ;
- `--symbol` et `--timeframe` sont pris en compte ;
- `--start` / `--end` filtrent la période ;
- période inversée, fichier absent, CSV vide, colonnes manquantes, CSV désordonné, données insuffisantes → code 1 et message clair ;
- erreur de téléchargement CCXT → code 1 ;
- `--save-csv` écrit le cache local ;
- configuration invalide → code 1 sans traceback ;
- options de backtest sans `--backtest` → erreur d'usage.

## Ce que les tests ne couvrent pas

- Le téléchargement réel depuis Binance Testnet (réseau et disponibilité de l'historique) : il est testé par simulation, pas en conditions réelles.
- Le paper trading et l'exécution d'ordres, non implémentés.
- Le rendu visuel du rapport dans un terminal particulier.

## Étape manuelle : backtest sur données réelles

Faire tourner la stratégie sur 1 à 2 ans de bougies horaires, puis vérifier :

- rendement total et comparaison avec le buy & hold ;
- nombre de trades et taux de réussite ;
- drawdown maximal ;
- cohérence entre PnL net, frais et capital final.

Un backtest qui ne bat pas le buy & hold après frais n'apporte pas de valeur : c'est une information, pas un échec technique.

## Étape suivante : paper trading

Le bot tourne en temps réel avec de l'argent fictif pendant au moins 2 à 4 semaines. On vérifie l'absence de plantage, la gestion des coupures réseau, la complétude du journal et la proximité des résultats avec le backtest.

## Décision

Le passage à l'argent réel n'est pas au programme de cette version. Il exigerait toutes les étapes concluantes, une surveillance quotidienne et des règles de risque identiques.
