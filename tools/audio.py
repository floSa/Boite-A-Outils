"""Outils audio : normalisation FLAC, extraction depuis vidéo, renommage par tags."""

from __future__ import annotations

import shutil
import tempfile
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from tools.ffmpeg_utils import lancer_ffmpeg
from tools.files import Renommage, nettoyer_nom

# --- A1 : normalisation FLAC -------------------------------------------------

EXT_VIDEO = (".mp4", ".mkv", ".mov", ".avi", ".webm", ".m4v")


@dataclass
class InfoFlac:
    chemin: Path
    sample_rate: int
    bits: int


def info_flac(path: str | Path) -> InfoFlac:
    """Lit fréquence d'échantillonnage et profondeur de bits d'un FLAC (via mutagen)."""
    from mutagen.flac import FLAC

    audio = FLAC(str(path))
    return InfoFlac(
        chemin=Path(path),
        sample_rate=audio.info.sample_rate,
        bits=audio.info.bits_per_sample,
    )


def besoin_normalisation(
    info: InfoFlac, sr_max: int = 44100, bits_max: int = 16
) -> bool:
    return info.sample_rate > sr_max or info.bits > bits_max


def normaliser_flac(
    path: str | Path, *, sr_cible: int = 44100, bits_cible: int = 16
) -> None:
    """Ré-encode un FLAC en 16 bit/44.1 kHz **sur place**, métadonnées préservées."""
    src = Path(path)
    fmt = {16: "s16", 24: "s32"}.get(bits_cible, "s16")
    with tempfile.TemporaryDirectory() as tmp:
        sortie = Path(tmp) / src.name
        lancer_ffmpeg(
            [
                "-i",
                str(src),
                "-sample_fmt",
                fmt,
                "-ar",
                str(sr_cible),
                "-map_metadata",
                "0",
                "-c:a",
                "flac",
                str(sortie),
            ]
        )
        sortie.replace(src)  # remplace l'original


def normaliser_dossier(
    dossier: str | Path,
    *,
    recursif: bool = True,
    sr_max: int = 44100,
    bits_max: int = 16,
    log: Callable[[str], None] | None = None,
) -> list[Path]:
    """Normalise tous les FLAC haute résolution d'un dossier. Retourne les fichiers traités."""
    base = Path(dossier)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    fichiers = base.rglob("*.flac") if recursif else base.glob("*.flac")
    traites: list[Path] = []
    for f in sorted(fichiers):
        info = info_flac(f)
        if besoin_normalisation(info, sr_max, bits_max):
            if log:
                log(
                    f"Normalisation : {f.name} ({info.sample_rate} Hz / {info.bits} bit)"
                )
            normaliser_flac(f, sr_cible=sr_max, bits_cible=bits_max)
            traites.append(f)
    return traites


# --- A2 : extraction de l'audio d'une vidéo ----------------------------------

CODECS_AUDIO = {
    "flac": ["-c:a", "flac"],
    "mp3": ["-c:a", "libmp3lame", "-q:a", "2"],
    "wav": ["-c:a", "pcm_s16le"],
    "m4a": ["-c:a", "aac", "-b:a", "256k"],
}


def extraire_audio(
    video_path: str | Path,
    format_sortie: str = "flac",
    dossier_sortie: str | Path | None = None,
) -> Path:
    """Extrait la piste audio d'une vidéo vers un fichier audio (sans ré-encoder la vidéo)."""
    src = Path(video_path)
    if not src.is_file():
        raise FileNotFoundError(f"Vidéo introuvable : {src}")
    if format_sortie not in CODECS_AUDIO:
        raise ValueError(
            f"Format non géré : {format_sortie} (choix : {', '.join(CODECS_AUDIO)})"
        )

    dossier = Path(dossier_sortie) if dossier_sortie else src.parent
    dossier.mkdir(parents=True, exist_ok=True)
    sortie = dossier / f"{src.stem}.{format_sortie}"

    lancer_ffmpeg(["-i", str(src), "-vn", *CODECS_AUDIO[format_sortie], str(sortie)])
    return sortie


# --- A3 : renommage depuis les tags ------------------------------------------

EXT_AUDIO = (".mp3", ".flac", ".m4a", ".ogg", ".opus", ".wav")


def _tags(path: Path) -> dict[str, str]:
    """Lit quelques tags usuels (artiste, titre, album, piste, année) via mutagen."""
    from mutagen import File as MutaFile

    audio = MutaFile(str(path), easy=True)
    if audio is None:
        return {}

    def prem(cle: str) -> str:
        v = audio.get(cle)
        return str(v[0]) if v else ""

    piste = prem("tracknumber").split("/")[0]
    annee = prem("date")[:4]
    return {
        "artiste": prem("artist"),
        "titre": prem("title"),
        "album": prem("album"),
        "piste": piste,
        "annee": annee,
    }


def nom_depuis_tags(tags: dict[str, str], motif: str) -> str:
    """Construit un nom de fichier depuis un motif, ex. ``{piste} - {artiste} - {titre}``.

    La piste est complétée sur 2 chiffres ; les champs manquants deviennent vides.
    """
    champs = dict(tags)
    piste = champs.get("piste", "")
    champs["piste"] = f"{int(piste):02d}" if piste.isdigit() else piste
    from collections import defaultdict

    nom = motif.format_map(defaultdict(str, champs))
    return nettoyer_nom(nom, minuscule=False, espaces_en=" ").strip()


def previsualiser_renommage_tags(
    dossier: str | Path,
    motif: str = "{piste} - {artiste} - {titre}",
    *,
    recursif: bool = False,
) -> list[Renommage]:
    """Calcule les renommages basés sur les tags, sans rien modifier."""
    base = Path(dossier)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    fichiers = base.rglob("*") if recursif else base.iterdir()
    renommages: list[Renommage] = []
    for f in sorted(fichiers):
        if not f.is_file() or f.suffix.lower() not in EXT_AUDIO:
            continue
        tags = _tags(f)
        base_nom = nom_depuis_tags(tags, motif)
        if not base_nom:
            continue
        cible = f.with_name(base_nom + f.suffix.lower())
        if cible != f:
            renommages.append(Renommage(ancien=f, nouveau=cible))
    return renommages


# --- A4 : convertir un format audio ------------------------------------------


def convertir_audio(
    src: str | Path,
    format_sortie: str,
    *,
    bitrate: str | None = None,
    dossier_sortie: str | Path | None = None,
) -> Path:
    """Convertit un fichier audio vers un autre format.

    :param format_sortie: ``flac``, ``mp3``, ``wav`` ou ``m4a``.
    :param bitrate: pour les formats avec perte, ex. ``"320k"`` (sinon défaut du codec).
    """
    source = Path(src)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    if format_sortie not in CODECS_AUDIO:
        raise ValueError(
            f"Format non géré : {format_sortie} (choix : {', '.join(CODECS_AUDIO)})"
        )

    dossier = Path(dossier_sortie) if dossier_sortie else source.parent
    dossier.mkdir(parents=True, exist_ok=True)
    sortie = dossier / f"{source.stem}.{format_sortie}"
    if sortie.resolve() == source.resolve():
        sortie = dossier / f"{source.stem}_converti.{format_sortie}"

    codec = list(CODECS_AUDIO[format_sortie])
    if bitrate and format_sortie in ("mp3", "m4a"):
        # Remplace la qualité VBR par un bitrate constant si demandé.
        codec = ["-c:a", codec[1], "-b:a", bitrate]
    lancer_ffmpeg(["-i", str(source), "-map_metadata", "0", *codec, str(sortie)])
    return sortie


# --- A5 : découper un passage audio ------------------------------------------


def decouper_audio(
    src: str | Path, debut: str, fin: str, sortie: str | Path | None = None
) -> Path:
    """Extrait le passage [debut, fin] d'un audio (sans ré-encoder). Horodatages HH:MM:SS."""
    source = Path(src)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    cible = (
        Path(sortie)
        if sortie
        else source.with_name(f"{source.stem}_extrait{source.suffix}")
    )
    lancer_ffmpeg(
        [
            "-ss",
            str(debut),
            "-to",
            str(fin),
            "-i",
            str(source),
            "-c",
            "copy",
            str(cible),
        ]
    )
    return cible


# --- A6 : éditer les tags en masse -------------------------------------------

CHAMPS_TAGS = ("artist", "albumartist", "album", "date", "genre")


def editer_tags(
    dossier: str | Path, tags: dict[str, str], *, recursif: bool = False
) -> int:
    """Applique des tags (champs non vides de ``tags``) à tous les audios d'un dossier.

    Champs reconnus : artist, albumartist, album, date, genre. Retourne le nb traité.
    """
    from mutagen import File as MutaFile

    base = Path(dossier)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    a_poser = {k: v for k, v in tags.items() if k in CHAMPS_TAGS and v}
    if not a_poser:
        return 0

    fichiers = base.rglob("*") if recursif else base.iterdir()
    n = 0
    for f in sorted(fichiers):
        if not f.is_file() or f.suffix.lower() not in EXT_AUDIO:
            continue
        audio = MutaFile(str(f), easy=True)
        if audio is None:
            continue
        for k, v in a_poser.items():
            audio[k] = v
        audio.save()
        n += 1
    return n


# --- A7 : normaliser le volume (loudness) ------------------------------------


def normaliser_volume(
    src: str | Path, *, cible_lufs: float = -14.0, sortie: str | Path | None = None
) -> Path:
    """Normalise le volume perçu (loudnorm EBU R128) vers une cible LUFS."""
    source = Path(src)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    cible = (
        Path(sortie)
        if sortie
        else source.with_name(f"{source.stem}_norm{source.suffix}")
    )
    lancer_ffmpeg(
        [
            "-i",
            str(source),
            "-af",
            f"loudnorm=I={cible_lufs}:TP=-1.5:LRA=11",
            "-map_metadata",
            "0",
            str(cible),
        ]
    )
    return cible


# --- A8 : convertir en FLAC (remplacement) -----------------------------------

EXT_AUDIO_NON_FLAC = (
    ".mp3",
    ".m4a",
    ".wav",
    ".ogg",
    ".opus",
    ".wma",
    ".aac",
    ".aiff",
    ".alac",
)


def inventaire_non_flac(
    dossier: str | Path,
    *,
    recursif: bool = True,
    extensions: tuple[str, ...] | None = None,
) -> list[Path]:
    """Dresse l'inventaire des fichiers audio non-FLAC d'un dossier.

    :param dossier: chemin du dossier à analyser.
    :param recursif: descend dans les sous-dossiers si vrai.
    :param extensions: extensions ciblées (défaut : EXT_AUDIO_NON_FLAC).
    :return: liste triée des chemins de fichiers trouvés.
    """
    base = Path(dossier)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    exts = tuple(e.lower() for e in (extensions or EXT_AUDIO_NON_FLAC))
    fichiers = base.rglob("*") if recursif else base.iterdir()
    candidats: list[Path] = []
    for f in fichiers:
        if f.is_file() and not f.name.startswith((".", "_")):
            if f.suffix.lower() in exts:
                candidats.append(f)
    return sorted(candidats)


def convertir_en_flac(src: str | Path, *, remplacer: bool = True) -> Path:
    """Convertit un fichier audio vers le format FLAC avec conservation des métadonnées.

    Si ``remplacer`` est vrai, le fichier source d'origine est supprimé après confirmation
    de la conversion sans erreur.

    :param src: fichier audio à convertir.
    :param remplacer: remplace le fichier source par le FLAC obtenu.
    :return: chemin du fichier FLAC produit.
    """
    source = Path(src)
    if not source.is_file():
        raise FileNotFoundError(f"Fichier introuvable : {source}")
    cible = source.with_suffix(".flac")
    if source.resolve() == cible.resolve():
        return source

    with tempfile.TemporaryDirectory() as tmp:
        sortie_tmp = Path(tmp) / cible.name
        lancer_ffmpeg(
            [
                "-i",
                str(source),
                "-map_metadata",
                "0",
                "-c:a",
                "flac",
                str(sortie_tmp),
            ]
        )
        if not sortie_tmp.is_file() or sortie_tmp.stat().st_size == 0:
            raise RuntimeError(f"Échec de la conversion en FLAC : {source}")
        shutil.move(str(sortie_tmp), str(cible))
        if remplacer and source.exists() and source.resolve() != cible.resolve():
            source.unlink()
    return cible


@dataclass
class ResultatConversionFlac:
    convertis: list[tuple[Path, Path]] = field(default_factory=list)
    erreurs: list[tuple[Path, str]] = field(default_factory=list)


def convertir_dossier_flac(
    fichiers: list[Path],
    *,
    remplacer: bool = True,
    log: Callable[[str], None] | None = None,
) -> ResultatConversionFlac:
    """Convertit une série de fichiers audio en FLAC.

    :param fichiers: liste des chemins à convertir.
    :param remplacer: remplace les fichiers d'origine par le FLAC.
    :param log: fonction de suivi / callback d'affichage.
    :return: objet ResultatConversionFlac avec les réussites et erreurs.
    """
    resultat = ResultatConversionFlac()
    for f in fichiers:
        try:
            if log:
                try:
                    log(f"Conversion : {f.name}")
                except UnicodeEncodeError:
                    log(
                        f"Conversion : {f.name.encode('ascii', 'replace').decode('ascii')}"
                    )
            dst = convertir_en_flac(f, remplacer=remplacer)
            resultat.convertis.append((f, dst))
        except Exception as e:
            if log:
                log(f"Erreur sur {f.name} : {e}")
            resultat.erreurs.append((f, str(e)))
    return resultat
