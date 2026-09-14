"""Outils de téléchargement de vidéos en ligne via yt-dlp.

Prend en charge YouTube, Facebook, Dailymotion, Instagram, TikTok, Twitter/X, etc.
Utilise le binaire ffmpeg embarqué par le projet pour l'assemblage et l'extraction audio.
"""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from tools.ffmpeg_utils import chemin_ffmpeg

logger = logging.getLogger(__name__)


def formater_duree(secondes: float | int | None) -> str:
    """Formate une durée en secondes en chaîne HH:MM:SS ou MM:SS."""
    if secondes is None:
        return "Inconnue"
    s = int(secondes)
    h = s // 3600
    m = (s % 3600) // 60
    reste_s = s % 60
    if h > 0:
        return f"{h:02d}:{m:02d}:{reste_s:02d}"
    return f"{m:02d}:{reste_s:02d}"


def recuperer_infos(url: str) -> dict[str, Any]:
    """Extrait les métadonnées d'une vidéo (titre, durée, miniature, etc.) sans la télécharger.

    :param url: URL de la vidéo web.
    :return: Dictionnaire contenant titre, durée, auteur, miniature, etc.
    :raises ValueError: si l'URL est invalide ou non prise en charge.
    """
    if not url or not url.strip():
        raise ValueError("L'URL fournie est vide.")

    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            infos = ydl.extract_info(url.strip(), download=False)
            if not infos:
                raise ValueError(
                    "Impossible de récupérer les informations de la vidéo."
                )

            return {
                "titre": infos.get("title", "Sans titre"),
                "auteur": infos.get("uploader")
                or infos.get("channel", "Auteur inconnu"),
                "duree_secondes": infos.get("duration"),
                "duree_formatee": formater_duree(infos.get("duration")),
                "miniature": infos.get("thumbnail"),
                "description": infos.get("description", ""),
                "url": url.strip(),
            }
    except yt_dlp.utils.DownloadError as e:
        logger.error(
            "Erreur lors de la récupération des métadonnées pour %s : %s", url, e
        )
        raise ValueError(f"Erreur lors de l'accès à la vidéo : {e}") from e


def telecharger_video(
    url: str,
    dossier_destination: str | Path,
    *,
    qualite: str = "meilleure",
    nom_fichier: str | None = None,
    progression: Callable[[dict[str, Any]], None] | None = None,
) -> Path:
    """Télécharge une vidéo ou son audio vers un dossier local.

    :param url: URL de la vidéo à télécharger.
    :param dossier_destination: Dossier où enregistrer le fichier.
    :param qualite: "meilleure", "1080p", "720p" ou "audio".
    :param nom_fichier: Nom de fichier optionnel (par défaut: titre de la vidéo).
    :param progression: Callback de progression recevant le dictionnaire d'état yt-dlp.
    :return: Chemin complet (Path) du fichier téléchargé.
    :raises NotADirectoryError: si le dossier de destination n'existe pas.
    :raises ValueError: si l'URL ou la qualité est invalide.
    """
    dest = Path(dossier_destination)
    if not dest.is_dir():
        raise NotADirectoryError(f"Le dossier de destination n'existe pas : {dest}")

    if not url or not url.strip():
        raise ValueError("L'URL fournie est vide.")

    # Modèle de nom de sortie
    if nom_fichier and nom_fichier.strip():
        stem = Path(nom_fichier.strip()).stem
        modele_sortie = str(dest / f"{stem}.%(ext)s")
    else:
        modele_sortie = str(dest / "%(title)s.%(ext)s")

    ffmpeg_bin = chemin_ffmpeg()

    opts: dict[str, Any] = {
        "outtmpl": modele_sortie,
        "ffmpeg_location": ffmpeg_bin,
        "quiet": True,
        "no_warnings": True,
        "windowsfilenames": True,
    }

    if progression:
        opts["progress_hooks"] = [progression]

    if qualite == "audio":
        opts.update(
            {
                "format": "bestaudio/best",
                "postprocessors": [
                    {
                        "key": "FFmpegExtractAudio",
                        "preferredcodec": "mp3",
                        "preferredquality": "192",
                    }
                ],
            }
        )
    elif qualite == "1080p":
        opts.update(
            {
                "format": "bestvideo[height<=1080]+bestaudio/best[height<=1080]/best",
                "merge_output_format": "mp4",
            }
        )
    elif qualite == "720p":
        opts.update(
            {
                "format": "bestvideo[height<=720]+bestaudio/best[height<=720]/best",
                "merge_output_format": "mp4",
            }
        )
    elif qualite == "meilleure":
        opts.update(
            {
                "format": "bestvideo+bestaudio/best",
                "merge_output_format": "mp4",
            }
        )
    else:
        raise ValueError(
            f"Qualité non reconnue : {qualite}. Choix possibles : 'meilleure', '1080p', '720p', 'audio'."
        )

    fichiers_telecharges: list[str] = []

    def _intercepter_nom(d: dict[str, Any]) -> None:
        if d.get("status") == "finished" and "filename" in d:
            fichiers_telecharges.append(d["filename"])

    opts.setdefault("progress_hooks", []).append(_intercepter_nom)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            infos = ydl.extract_info(url.strip(), download=True)
            if not infos:
                raise RuntimeError("Aucune donnée téléchargée.")

            # Détermination du chemin final
            if qualite == "audio":
                nom_base = ydl.prepare_filename(infos)
                chemin_final = Path(nom_base).with_suffix(".mp3")
            else:
                nom_base = ydl.prepare_filename(infos)
                # Si merge_output_format est mp4, le conteneur final est mp4
                chemin_final = Path(nom_base).with_suffix(".mp4")
                if not chemin_final.exists() and Path(nom_base).exists():
                    chemin_final = Path(nom_base)

            # Si le fichier existe, on le retourne
            if chemin_final.exists():
                return chemin_final

            # Repli sur les fichiers captés par le hook
            for f in reversed(fichiers_telecharges):
                pf = Path(f)
                if pf.exists():
                    return pf

            return chemin_final

    except yt_dlp.utils.DownloadError as e:
        logger.error("Erreur lors du téléchargement de %s : %s", url, e)
        raise RuntimeError(f"Échec du téléchargement : {e}") from e
