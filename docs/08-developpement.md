# Guide de développement

## Environnement

- Python 3.11 ou supérieur ;
- environnement virtuel `.venv` ;
- dépendances déclarées dans `pyproject.toml` (`ccxt`, `python-dotenv`, plus `pytest` et `ruff` en extra `dev`).

```bash
pip install -e ".[dev]"
pytest
ruff check .
```

## Structure

```text
src/tradebot/
├── backtesting/
│   ├── data_loader.py   # CSV local et téléchargement CCXT
│   ├── engine.py        # simulation bougie par bougie
│   └── metrics.py       # métriques et rapport
├── domain/models.py     # Candle, Signal, TradeDecision
├── exchange/            # lecture Testnet (aucun ordre)
├── portfolio/           # portefeuille virtuel (paper trading)
├── risk/manager.py      # dimensionnement et limite journalière
├── storage/journal.py   # journal CSV
├── strategy/            # indicateurs et signaux
├── app.py               # analyse ponctuelle
├── cli.py               # commande trade-bot
└── config.py            # paramètres validés
```

## Règles

- Une responsabilité par module.
- La stratégie ne doit jamais appeler l'exchange ni le portefeuille.
- Les tests unitaires ne doivent pas dépendre du réseau.
- Toute règle de risque doit avoir un test.
- Aucun secret dans Git.
- Aucune exécution réelle dans cette version.

## Convention de backtest à respecter

Toute modification du moteur doit préserver ces invariants :

1. **Signal sur bougie clôturée, exécution à l'ouverture suivante.** Ne jamais exécuter au prix de clôture qui a produit le signal.
2. **Frais à l'achat et à la vente**, inclus dans le PnL net.
3. **Slippage défavorable** sur chaque exécution.
4. **Gap sous le stop** : exécution à l'ouverture, pas au niveau du stop.
5. **Solde jamais négatif** ; les frais d'achat tiennent dans le budget.
6. **Position finale liquidée** à la clôture de la dernière bougie (`end_of_data`).
7. **Limite journalière sur l'equity**, réinitialisée à minuit UTC, qui bloque seulement les nouvelles entrées.

Un test doit couvrir chacun de ces points (`tests/test_backtest_engine.py`).

## Ajouter une stratégie

1. Créer un module dans `src/tradebot/strategy/` exposant une fonction pure :

   ```python
   from collections.abc import Sequence
   from tradebot.domain.models import Signal


   def my_signal(closes: Sequence[float]) -> Signal:
       """Retourne BUY, SELL ou HOLD à partir des clôtures disponibles."""
       ...
   ```

2. La fonction ne doit recevoir que des données déjà clôturées et ne jamais appeler l'exchange.
3. Ajouter les tests unitaires correspondants (signal haussier, baissier, aucun signal, données insuffisantes).
4. Pour l'utiliser dans le backtest, remplacer l'appel à `crossover_signal` dans `run_backtest` — ou passer la fonction en paramètre si plusieurs stratégies doivent cohabiter. Éviter de dupliquer la boucle de simulation.
5. Documenter la règle dans `docs/02-strategie.md`.

## Ajouter un champ de configuration

1. Ajouter l'attribut à `Settings` dans `config.py`.
2. Le lire depuis l'environnement dans `from_env`, avec une valeur par défaut.
3. Valider la valeur et lever `ValueError` si elle est hors bornes.
4. Ajouter la variable dans `.env.example`.
5. Ajouter un test si la validation est non triviale.

## Tests et intégration continue

- `pytest` exécute toute la suite (`testpaths = ["tests"]`, `pythonpath = [".", "src"]`).
- `ruff check .` applique les règles `F, E, W, I, UP, B, SIM` avec une largeur de 100 caractères.
- `.github/workflows/tests.yml` installe Python 3.11, le projet et les dépendances de développement, puis exécute Ruff et pytest. Une erreur de lint ou un test en échec fait échouer la CI.

## Commits

Utiliser des préfixes explicites : `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

Développer sur une branche dédiée puis ouvrir une Pull Request vers `main`.

## Sécurité

- `DRY_RUN=true` reste la valeur par défaut.
- Aucune fonction d'envoi d'ordre n'est implémentée ; ne pas en ajouter dans cette version.
- Ne jamais demander ni stocker de clé API avec droit de retrait.
- Le backtest doit continuer à fonctionner sans aucune clé.
