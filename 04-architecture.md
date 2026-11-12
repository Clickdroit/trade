# 4. Architecture technique

## Outils
- Python 3
- `ccxt` : connexion à l'exchange
- `pandas` : calcul des moyennes mobiles
- `python-dotenv` : lecture des clés API depuis `.env`
- Fichier CSV pour le journal des trades

## Organisation des fichiers
```
trade/
├── .env            (clés API, jamais sur GitHub)
├── .gitignore
├── config.py       (paramètres : paire, MM, risque)
├── data.py         (récupère les prix)
├── strategy.py     (calcule le signal)
├── trader.py       (passe les ordres)
├── journal.py      (enregistre les trades)
├── backtest.py     (teste sur l'historique)
├── main.py         (boucle principale)
└── docs/           (cette documentation)
```

## Rôle de chaque module
- **config.py** : tous les réglages au même endroit
- **data.py** : demande les dernières bougies à l'exchange
- **strategy.py** : renvoie « ACHAT », « VENTE » ou « ATTENTE »
- **trader.py** : envoie l'ordre et applique le stop-loss
- **journal.py** : ajoute une ligne dans le CSV à chaque décision
- **main.py** : enchaîne tout en boucle

## Boucle principale
1. Récupérer les prix (data)
2. Calculer le signal (strategy)
3. Vérifier les règles de risque (trader)
4. Passer l'ordre si besoin (trader)
5. Écrire dans le journal (journal)
6. Attendre l'intervalle suivant, puis recommencer

## Exemple très simple (strategy.py)
```python
def calculer_signal(prix):
    # prix = liste des prix de clôture
    mm_courte = sum(prix[-10:]) / 10
    mm_longue = sum(prix[-30:]) / 30

    if mm_courte > mm_longue:
        return "ACHAT"
    elif mm_courte < mm_longue:
        return "VENTE"
    else:
        return "ATTENTE"
```
Cette version compare l'état actuel des deux moyennes. La détection du croisement exact sera ajoutée au développement.
