"""Gestion centralisée des journaux d'annulation (fichiers undo) de l'application.

Tous les journaux d'annulation sont stockés côté application (dans `.undo_logs/` à la
racine du projet Boite-A-Outils ou dans le dossier de configuration utilisateur),
et JAMAIS dans les dossiers musicaux ou répertoires de travail de l'utilisateur.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path


def _dossier_undo_app() -> Path:
    """Renvoie le dossier où sont stockés tous les journaux d'annulation de l'application."""
    # Stocké dans .undo_logs à la racine du dépôt Boite-A-Outils
    base = Path(__file__).resolve().parent.parent / ".undo_logs"
    base.mkdir(parents=True, exist_ok=True)
    return base


def get_chemin_journal(racine: str | Path, nom_outil: str) -> Path:
    """Calcule le chemin unique du fichier journal côté application pour un dossier cible donné.

    :param racine: Le dossier cible sur lequel porte l'opération.
    :param nom_outil: L'identifiant de l'outil (ex: 'singles', 'doublons', 'regrouper', 'nettoyer').
    :return: Le chemin complet du fichier JSON d'annulation côté application.
    """
    p = Path(racine).resolve()
    # Empreinte basée sur le chemin absolu normalisé
    hash_chemin = hashlib.sha256(str(p).lower().encode("utf-8")).hexdigest()[:12]
    nom_fichier = f"{nom_outil}_{hash_chemin}.undo.json"
    return _dossier_undo_app() / nom_fichier
