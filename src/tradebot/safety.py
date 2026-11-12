"""Garde-fous anti-exécution réelle.

Le projet reste un simulateur : aucune fonction de ce dépôt n'envoie d'ordre.
Ces protections sont volontairement redondantes (configuration, client de
marché) afin qu'une erreur de configuration ne puisse pas activer un mode réel.

Rappel : Binance Testnet n'est utilisé que pour les **données publiques**.
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

#: Unique mode d'exécution autorisé par ce projet.
PAPER_MODE = "paper"

#: Modes explicitement interdits (aucun n'est implémenté).
FORBIDDEN_MODES = frozenset({"live", "real", "prod", "production", "binance"})


class LiveTradingForbiddenError(RuntimeError):
    """Une tentative d'exécution réelle (ou un mode inconnu) a été détectée."""


def assert_paper_mode(mode: str) -> None:
    """Refuse tout mode d'exécution autre que ``paper``.

    Raises:
        LiveTradingForbiddenError: Mode réel ou inconnu.
    """
    normalized = mode.strip().lower()
    if normalized in FORBIDDEN_MODES:
        raise LiveTradingForbiddenError(
            f"Mode d'exécution {mode!r} interdit : ce projet ne passe aucun ordre réel "
            f"et ne supporte que {PAPER_MODE!r}."
        )
    if normalized != PAPER_MODE:
        raise LiveTradingForbiddenError(
            f"Mode d'exécution inconnu : {mode!r}. Seul {PAPER_MODE!r} est supporté."
        )


def assert_public_market_client(client: object) -> None:
    """Vérifie qu'un client CCXT est un client public, sans credentials.

    Un client authentifié pourrait, en cas d'évolution du code, avoir accès à des
    endpoints privés. On refuse donc par principe tout client porteur de clés.

    Raises:
        LiveTradingForbiddenError: Le client porte une clé API ou un secret.
    """
    api_key = getattr(client, "apiKey", None)
    secret = getattr(client, "secret", None)
    if api_key or secret:
        raise LiveTradingForbiddenError(
            "Client CCXT authentifié refusé : le Paper Trading n'utilise que des "
            "données publiques et ne doit jamais disposer de clés API."
        )


def assert_no_real_funds(settings_dry_run: bool) -> None:
    """Refuse un démarrage si ``DRY_RUN`` n'est pas actif.

    Raises:
        LiveTradingForbiddenError: ``DRY_RUN`` désactivé.
    """
    if not settings_dry_run:
        raise LiveTradingForbiddenError(
            "DRY_RUN=false interdit : ce projet ne doit jamais manipuler de fonds réels."
        )
