# Bot de trading crypto

Projet d'apprentissage : un bot en Python qui trade le BTC/USDT sur le **testnet Binance** (argent fictif) avec une stratégie simple de croisement de moyennes mobiles.

> ⚠️ Le bot reste en **simulation**. Aucune stratégie ne garantit des gains et le trading réel peut faire perdre de l'argent.

## Documentation

| Fichier | Contenu |
|---|---|
| [docs/01-cahier-des-charges.md](docs/01-cahier-des-charges.md) | Objectifs, périmètre, contraintes |
| [docs/02-strategie.md](docs/02-strategie.md) | Règles d'achat et de vente |
| [docs/03-gestion-risque.md](docs/03-gestion-risque.md) | Limites de perte, stop-loss, sécurité |
| [docs/04-architecture.md](docs/04-architecture.md) | Outils, fichiers, boucle principale |
| [docs/05-plan-de-tests.md](docs/05-plan-de-tests.md) | Tests, backtest, simulation |
| [docs/06-journal-suivi.md](docs/06-journal-suivi.md) | Journal des trades, bilan hebdo |
| [docs/07-planning-risques.md](docs/07-planning-risques.md) | Planning et risques du projet |

## Choix de départ

- Marché : crypto, paire BTC/USDT
- Langage : Python 3
- Mode : testnet uniquement
- Stratégie : croisement de moyennes mobiles (10 et 30)

## Sécurité

Les clés API vont dans un fichier `.env` qui n'est **jamais** envoyé sur GitHub (voir `.gitignore`). Utiliser un modèle : `.env.example`.

## Prochaine étape

Créer le compte testnet Binance, générer les clés API, puis écrire `data.py`.
