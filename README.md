# Trade — Bot de trading crypto éducatif

Bot Python d'apprentissage pour analyser BTC/USDT avec une stratégie de croisement de moyennes mobiles. Le projet démarre en **lecture de marché et simulation** sur Binance Spot Testnet.

> **Sécurité :** aucune exécution d'ordre réel n'est implémentée. Aucune stratégie ne garantit des gains. Le trading comporte un risque de perte.

## État du projet

- [x] Cahier des charges et stratégie initiale
- [x] Architecture Python en modules
- [x] Calcul du croisement MM10/MM30
- [x] Premiers tests unitaires
- [x] Garde-fous de risque de base
- [ ] Backtest avec frais et slippage
- [ ] Paper trading avec portefeuille virtuel
- [ ] Connexion testnet avec ordres fictifs, après validation
- [ ] Monitoring et arrêt d'urgence

## Installation Windows (PowerShell)

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
pip install -e ".[dev]"
Copy-Item .env.example .env
pytest
```

Sous Linux/macOS : `source .venv/bin/activate`.

## Lancer une analyse ponctuelle

```bash
trade-bot --once
```

Cette commande récupère des bougies publiques et affiche un signal. Elle ne passe aucun ordre.

## Configuration et sécurité

Les paramètres sont dans `.env`. Garde `DRY_RUN=true`. Les données publiques ne nécessitent aucune clé API. Ne colle jamais de clé secrète dans le code, les issues ou les conversations.

## Documentation

- [Cahier des charges](docs/01-cahier-des-charges.md)
- [Stratégie](docs/02-strategie.md)
- [Gestion du risque](docs/03-gestion-risque.md)
- [Architecture](docs/04-architecture.md)
- [Plan de tests](docs/05-plan-de-tests.md)
- [Journal et suivi](docs/06-journal-suivi.md)
- [Planning et risques](docs/07-planning-risques.md)
- [Guide de développement](docs/08-developpement.md)
