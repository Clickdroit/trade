# Guide de développement

## Environnement
- Python 3.11 ou supérieur
- Environnement virtuel `.venv`
- Dépendances déclarées dans `pyproject.toml`

## Commandes
```bash
pip install -e ".[dev]"
pytest
ruff check .
ruff format .
```

## Règles
- Une responsabilité par module.
- La stratégie ne doit pas appeler l'exchange.
- Les tests unitaires ne doivent pas dépendre du réseau.
- Toute règle de risque doit avoir un test.
- Aucun secret dans Git.
- Pas d'exécution réelle dans la V1.

## Commits
Utiliser des préfixes explicites : `feat:`, `fix:`, `docs:`, `test:`, `refactor:`, `chore:`.

Développer sur une branche dédiée puis ouvrir une Pull Request vers `main`.
