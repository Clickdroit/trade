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

### Portefeuille virtuel (`tests/test_portfolio.py`)

- ouverture : notionnel et frais déduits du solde ;
- fermeture : PnL brut, frais des deux côtés, PnL net, PnL réalisé cumulé ;
- invariant `equity = capital initial + réalisé + latent` ;
- refus d'une position dupliquée, d'un achat sans trésorerie, d'une vente sans position, d'une sortie antérieure à l'entrée ;
- drawdown et plus haut d'equity ;
- restauration depuis un état persisté et détection d'une trésorerie incohérente ;
- stop-loss unitaire (`check_stop_loss`).

### Broker simulé (`tests/test_paper_broker.py`)

- slippage défavorable à l'achat et à la vente ;
- frais prélevés sur le notionnel ;
- stop non atteint, stop au niveau, gap sous le stop exécuté à l'ouverture ;
- refus d'un second achat et d'une vente sans position ;
- paramètres invalides (slippage, prix de référence).

### Persistance SQLite (`tests/test_paper_store.py`)

- état et position conservés après fermeture/réouverture ;
- base vide → aucun état ;
- bougie déjà traitée → `DuplicateCandleError`, aucun doublon ;
- transaction dupliquée → rollback complet du cycle (décision et état inchangés) ;
- statut et drapeau d'arrêt ;
- réinitialisation et comptage des lignes supprimées ;
- historique d'equity ;
- schéma d'une version future refusé.

### Cycle de Paper Trading (`tests/test_paper_engine.py`)

- achat au signal, au prix de clôture, avec slippage ;
- vente au signal, avec frais et PnL net cohérent ;
- position non dupliquée sur un nouveau signal d'achat ;
- entrée refusée faute de capital ;
- stop-loss prioritaire sur le signal de vente ;
- gap sous le stop exécuté à l'ouverture ;
- stop non évalué sur la bougie d'entrée ;
- limite journalière : blocage des entrées, persistance après redémarrage, réarmement au changement de jour UTC ;
- limite journalière sans fermeture de position par défaut, fermeture si configurée ;
- bougie déjà traitée non retraitée ;
- reprise après redémarrage sans doublon de transaction ;
- erreur réseau → aucune transaction ;
- bougies invalides → aucune transaction ;
- état de portefeuille incohérent → `PortfolioStateError`, aucune transaction ;
- état enregistré pour une autre paire/timeframe refusé ;
- arrêt propre via le drapeau lu par l'exécution continue.

### Marché (`tests/test_market.py`)

- bougie en cours de formation exclue ;
- absence de bougie clôturée → erreur ;
- erreur réseau retentée puis erreur explicite après épuisement ;
- réponse vide, valeurs invalides, bougies désordonnées refusées ;
- client authentifié (clé API) refusé.

### Sécurité (`tests/test_safety.py`)

- tout mode autre que `paper` est refusé ;
- `DRY_RUN=false` refusé au chargement de la configuration ;
- limites de risque lues depuis l'environnement ;
- timeframe inconnu refusé.

### CLI Paper Trading (`tests/test_paper_cli.py`)

- `paper start --once` affiche un cycle et le statut ;
- `paper status` avant et après un cycle ;
- `paper history` liste les décisions ;
- `paper stop` pose le drapeau ;
- `paper reset` annulé sans confirmation, effectif avec `--yes` ;
- entrée standard fermée pendant la confirmation → aucune suppression.

## Ce que les tests ne couvrent pas

- Le téléchargement réel depuis Binance Testnet (réseau et disponibilité de l'historique) : il est testé par simulation, pas en conditions réelles.
- Le rendu visuel du rapport dans un terminal particulier.
- Un cycle réel de plusieurs heures en continu avec des données live : à faire manuellement (voir ci-dessous).

## Étape manuelle : backtest sur données réelles

Faire tourner la stratégie sur 1 à 2 ans de bougies horaires, puis vérifier :

- rendement total et comparaison avec le buy & hold ;
- nombre de trades et taux de réussite ;
- drawdown maximal ;
- cohérence entre PnL net, frais et capital final.

Un backtest qui ne bat pas le buy & hold après frais n'apporte pas de valeur : c'est une information, pas un échec technique.

## Étape suivante : paper trading en continu

Le bot tourne en temps réel avec de l'argent fictif pendant au moins 2 à 4 semaines. On vérifie l'absence de plantage, la gestion des coupures réseau, la complétude du journal, la cohérence du portefeuille après redémarrage et la proximité des résultats avec le backtest (sans exiger l'égalité : les prix d'exécution diffèrent).

```bash
python -m tradebot.cli paper start
python -m tradebot.cli paper status
python -m tradebot.cli paper history --limit 50
python -m tradebot.cli paper stop
```

## Décision

Le passage à l'argent réel n'est pas au programme de cette version. Il exigerait toutes les étapes concluantes, une surveillance quotidienne et des règles de risque identiques.
