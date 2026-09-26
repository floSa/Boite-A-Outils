"""Outils de téléchargement de vidéos en ligne via yt-dlp.

Prend en charge YouTube, Facebook, Dailymotion, Instagram, TikTok, Twitter/X, etc.
Utilise le binaire ffmpeg embarqué par le projet pour l'assemblage et l'extraction audio.
"""

from __future__ import annotations

import logging
import re
import urllib.request
from pathlib import Path
from typing import Any, Callable

import yt_dlp

from tools.ffmpeg_utils import chemin_ffmpeg

logger = logging.getLogger(__name__)


def normaliser_url(url: str) -> str:
    """Normalise certaines URLs spécifiques pour contourner des blocages régionaux."""
    u = url.strip()
    # Eporner : en France, les URLs directes /video-XXX/ sont interceptées par une page
    # de vérification d'âge qui empêche yt-dlp d'extraire le hash du lecteur.
    # L'URL d'intégration /embed/XXX contourne cette restriction sans altérer le flux vidéo.
    m = re.match(
        r"^https?://(?:www\.)?eporner\.com/(?:(?:hd-porn|embed)/|video-)([\w]+)",
        u,
        re.IGNORECASE,
    )
    if m:
        return f"https://www.eporner.com/embed/{m.group(1)}/"
    return u


def _extraire_titre_page(url_embed: str) -> str | None:
    """Tente de récupérer le titre HTML si l'extracteur yt-dlp renvoie 'Untitled'."""
    try:
        req = urllib.request.Request(url_embed, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=5) as resp:
            html = resp.read().decode("utf-8", "ignore")
            m = re.search(r"<title>(.+?)\s*-\s*EPORNER</title>", html, re.I)
            if m:
                return m.group(1).strip()
    except Exception:
        pass
    return None


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


def recuperer_infos(url: str, *, navigateur_cookies: str | None = None) -> dict[str, Any]:
    """Extrait les métadonnées d'une vidéo (titre, durée, miniature, etc.) sans la télécharger.

    :param url: URL de la vidéo web.
    :param navigateur_cookies: Nom du navigateur ("chrome", "firefox", "edge", "brave", ...)
        depuis lequel récupérer les cookies de session, nécessaire pour les vidéos qui
        exigent d'être connecté (ex. Vimeo privé). None pour ne pas utiliser de cookies.
    :return: Dictionnaire contenant titre, durée, auteur, miniature, etc.
    :raises ValueError: si l'URL est invalide ou non prise en charge.
    """
    if not url or not url.strip():
        raise ValueError("L'URL fournie est vide.")

    url_propre = normaliser_url(url)

    opts: dict[str, Any] = {
        "skip_download": True,
        "quiet": True,
        "no_warnings": True,
        "extract_flat": False,
    }
    if navigateur_cookies:
        opts["cookiesfrombrowser"] = (navigateur_cookies,)

    try:
        with yt_dlp.YoutubeDL(opts) as ydl:
            infos = ydl.extract_info(url_propre, download=False)
            if not infos:
                raise ValueError(
                    "Impossible de récupérer les informations de la vidéo."
                )

            titre = infos.get("title")
            if not titre or titre == "Untitled":
                titre = _extraire_titre_page(url_propre) or infos.get(
                    "description", "Sans titre"
                )

            return {
                "titre": titre,
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
    navigateur_cookies: str | None = None,
) -> Path:
    """Télécharge une vidéo ou son audio vers un dossier local.

    :param url: URL de la vidéo à télécharger.
    :param dossier_destination: Dossier où enregistrer le fichier.
    :param qualite: "meilleure", "1080p", "720p" ou "audio".
    :param nom_fichier: Nom de fichier optionnel (par défaut: titre de la vidéo).
    :param progression: Callback de progression recevant le dictionnaire d'état yt-dlp.
    :param navigateur_cookies: Nom du navigateur ("chrome", "firefox", "edge", "brave", ...)
        depuis lequel récupérer les cookies de session, nécessaire pour les vidéos qui
        exigent d'être connecté (ex. Vimeo privé). None pour ne pas utiliser de cookies.
    :return: Chemin complet (Path) du fichier téléchargé.
    :raises NotADirectoryError: si le dossier de destination n'existe pas.
    :raises ValueError: si l'URL ou la qualité est invalide.
    """
    dest = Path(dossier_destination)
    if not dest.is_dir():
        raise NotADirectoryError(f"Le dossier de destination n'existe pas : {dest}")

    if not url or not url.strip():
        raise ValueError("L'URL fournie est vide.")

    url_propre = normaliser_url(url)

    # Modèle de nom de sortie
    if nom_fichier and nom_fichier.strip():
        stem = Path(nom_fichier.strip()).stem
        modele_sortie = str(dest / f"{stem}.%(ext)s")
    else:
        titre_recup = (
            _extraire_titre_page(url_propre)
            if "eporner.com/embed/" in url_propre
            else None
        )
        if titre_recup:
            nom_nettoye = "".join(
                c for c in titre_recup if c not in r'\/:*?"<>|'
            ).strip()
            modele_sortie = str(dest / f"{nom_nettoye}.%(ext)s")
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
    if navigateur_cookies:
        opts["cookiesfrombrowser"] = (navigateur_cookies,)

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
            infos = ydl.extract_info(url_propre, download=True)
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
