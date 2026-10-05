"""Regrouper les « singles » d'une bibliothèque musicale.

Arborescence attendue : racine / <artiste> / <album> / fichiers.
Un dossier album qui ne contient **qu'un seul fichier audio** est un « single ».
L'outil :

- déplace le titre dans ``<artiste>/Singles/`` en retirant son numéro de piste
  (``01 - Ring Ring.flac`` → ``Singles/Ring Ring.flac``) ;
- déplace aussi les **fichiers non-image** du dossier (``.nfo``, ``.cue``, ``.lrc``,
  ``.pdf``…) dans ``Singles/``, renommés au titre ;
- **jette les images** (``.jpg``, ``.png``…) : elles restent dans le dossier vidé,
  qui part dans ``<racine>/_albums_vides_a_supprimer/`` — l'utilisateur supprime ce
  dossier d'un clic (interface web du NAS).

Aucun fichier n'est supprimé par l'outil : uniquement des déplacements. Journal
d'annulation. Un dossier contenant un sous-dossier (multi-disques, bonus) est
signalé « à vérifier » et laissé tel quel. Le numéro n'est retiré que s'il est suivi
d'un séparateur (``01 - Titre``) ou zéro-paddé (``01 Titre``), pour ne pas amputer un
titre comme ``99 Luftballons``.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from tools.undo_manager import get_chemin_journal

EXT_AUDIO = (
    ".flac",
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
# Images : jetées (non déplacées). Le reste (non-audio, non-image) suit le titre.
EXT_IMAGE = (".jpg", ".jpeg", ".png", ".webp", ".bmp", ".gif", ".tiff")
FICHIERS_JUNK = {"thumbs.db", ".ds_store", "desktop.ini"}
NOM_DOSSIER_SINGLES = "Singles"
NOM_CORBEILLE = "_albums_vides_a_supprimer"


def chemin_journal_singles(racine: str | Path) -> Path:
    """Renvoie le chemin du journal d'annulation des singles stocké côté application."""
    return get_chemin_journal(racine, "singles")

# Numéro de piste en tête : « 01 - », « 01. », « 01) », ou zéro-paddé « 01 », « 02 »…
_RE_NUM_PISTE = re.compile(r"^\s*(?:\d{1,3}\s*[-.)]\s*|0\d{1,2}\s+)")


def _titre_sans_numero(stem: str) -> str:
    """``01 - Ring Ring`` / ``01 Ring Ring`` → ``Ring Ring``. ``99 Luftballons`` inchangé."""
    return _RE_NUM_PISTE.sub("", stem).strip() or stem


@dataclass
class AlbumSingle:
    artiste: Path
    album: Path
    audio: Path
    a_deplacer: list[Path] = field(
        default_factory=list
    )  # fichiers non-image → Singles/
    autres: list[Path] = field(default_factory=list)  # sous-dossiers → « à vérifier »

    @property
    def a_verifier(self) -> bool:
        return bool(self.autres)


@dataclass
class Plan:
    a_traiter: list[AlbumSingle]
    a_verifier: list[AlbumSingle]


def _classer(album: Path) -> AlbumSingle | None:
    """AlbumSingle si le dossier contient exactement 1 audio, sinon None."""
    audios, sous_dossiers, a_deplacer = [], [], []
    try:
        with os.scandir(album) as it:
            for e in it:
                try:
                    est_dossier = e.is_dir()
                except OSError:
                    est_dossier = False
                if est_dossier:
                    sous_dossiers.append(Path(e.path))
                    continue
                ext = os.path.splitext(e.name)[1].lower()
                if ext in EXT_AUDIO:
                    audios.append(Path(e.path))
                elif ext in EXT_IMAGE or e.name.lower() in FICHIERS_JUNK:
                    pass  # images et junk : jetés (restent dans le dossier → corbeille)
                else:
                    a_deplacer.append(Path(e.path))  # autre fichier → suit le titre
    except OSError:
        return None

    if len(audios) != 1:
        return None  # vrai album (0 ou plusieurs audios) ou multi-disques
    return AlbumSingle(
        album.parent,
        album,
        audios[0],
        a_deplacer=sorted(a_deplacer),
        autres=sous_dossiers,
    )


def _sous_dossiers(chemin: Path) -> list[Path]:
    """Sous-dossiers directs, hors ``.``/``_`` (ignore la corbeille et le système)."""
    out: list[Path] = []
    try:
        with os.scandir(chemin) as it:
            for e in it:
                if e.name.startswith((".", "_")):
                    continue
                try:
                    if e.is_dir():
                        out.append(Path(e.path))
                except OSError:
                    continue
    except OSError:
        return []
    return sorted(out)


def analyser(
    racine: str | Path,
    *,
    progress: Callable[[int, int], None] | None = None,
) -> Plan:
    """Parcourt racine/<artiste>/<album> et classe les dossiers single.

    :param progress: rappelé après chaque artiste avec ``(traités, total)``.
    """
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    a_traiter: list[AlbumSingle] = []
    a_verifier: list[AlbumSingle] = []
    artistes = _sous_dossiers(base)
    total = len(artistes)
    for i, artiste in enumerate(artistes, 1):
        for album in _sous_dossiers(artiste):
            if album.name.lower() == NOM_DOSSIER_SINGLES.lower():
                continue
            sa = _classer(album)
            if sa is None:
                continue
            (a_verifier if sa.a_verifier else a_traiter).append(sa)
        if progress:
            progress(i, total)
    return Plan(a_traiter=a_traiter, a_verifier=a_verifier)


def _nom_libre(dossier: Path, nom: str, reserves: set[str]) -> Path:
    """Chemin cible non utilisé (ni sur disque, ni déjà réservé) ; suffixe (2), (3)…"""
    cible = dossier / nom
    if str(cible).lower() not in reserves and not cible.exists():
        reserves.add(str(cible).lower())
        return cible
    tige, ext = cible.stem, cible.suffix
    i = 2
    while True:
        cible = dossier / f"{tige} ({i}){ext}"
        if str(cible).lower() not in reserves and not cible.exists():
            reserves.add(str(cible).lower())
            return cible
        i += 1


@dataclass
class Mouvement:
    audio_src: Path
    audio_dst: Path
    annexes: list[tuple[Path, Path]] = field(
        default_factory=list
    )  # (src, dst) non-image


def previsualiser(plan: Plan) -> list[Mouvement]:
    """Calcule les destinations (sans rien déplacer), collisions résolues."""
    reserves: set[str] = set()
    mouvements: list[Mouvement] = []
    for sa in plan.a_traiter:
        singles = sa.artiste / NOM_DOSSIER_SINGLES
        titre = _titre_sans_numero(sa.audio.stem)
        audio_dst = _nom_libre(singles, titre + sa.audio.suffix.lower(), reserves)
        annexes = [
            (f, _nom_libre(singles, titre + f.suffix.lower(), reserves))
            for f in sa.a_deplacer
        ]
        mouvements.append(Mouvement(sa.audio, audio_dst, annexes))
    return mouvements


@dataclass
class ResultatSingles:
    journal: Path
    nb_singles: int
    nb_en_corbeille: int
    erreurs: list[str] = field(default_factory=list)


def appliquer(
    plan: Plan,
    racine: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> ResultatSingles:
    """Déplace titre + fichiers non-image dans Singles/, envoie le reste en corbeille.

    Ne supprime aucun fichier. Résilient : une erreur sur un single est collectée
    et le traitement continue.
    """

    def _log(m: str) -> None:
        if log:
            try:
                log(m)
            except UnicodeEncodeError:
                log(m.encode("ascii", "replace").decode("ascii"))

    journal: list[dict] = []
    erreurs: list[str] = []
    reserves_corbeille: set[str] = set()
    corbeille = Path(racine) / NOM_CORBEILLE
    nb_singles = nb_corbeille = 0

    for sa, mv in zip(plan.a_traiter, previsualiser(plan)):
        try:
            mv.audio_dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(mv.audio_src), str(mv.audio_dst))
            journal.append(
                {"type": "move", "de": str(mv.audio_dst), "vers": str(mv.audio_src)}
            )
            for src, dst in mv.annexes:
                shutil.move(str(src), str(dst))
                journal.append({"type": "move", "de": str(dst), "vers": str(src)})
        except OSError as e:
            erreurs.append(f"{sa.album} : {e}")
            continue
        nb_singles += 1

        # Nettoyage et suppression propre du dossier album vidé (fichiers junk résiduels supprimés)
        try:
            for root, _dirs, files in os.walk(sa.album):
                for f in files:
                    if f.lower() in FICHIERS_JUNK:
                        try:
                            (Path(root) / f).unlink(missing_ok=True)
                        except OSError:
                            pass
            shutil.rmtree(sa.album)
            journal.append({"type": "rmdir", "path": str(sa.album)})
            nb_corbeille += 1
            _log(f"✓ {sa.album.name} (album vidé nettoyé) → {NOM_DOSSIER_SINGLES}/")
        except OSError as e:
            erreurs.append(f"{sa.album} (nettoyage dossier) : {e}")

    chemin = chemin_journal_singles(racine)
    try:
        chemin.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        erreurs.append(f"Journal d'annulation non écrit ({chemin}) : {e}")
    return ResultatSingles(
        journal=chemin,
        nb_singles=nb_singles,
        nb_en_corbeille=nb_corbeille,
        erreurs=erreurs,
    )


def annuler(racine: str | Path) -> int:
    """Restaure l'état précédent depuis le journal. Retourne le nombre d'actions annulées."""
    chemin = chemin_journal_singles(racine)
    if not chemin.is_file():
        raise FileNotFoundError(f"Aucun journal d'annulation pour {racine}")

    entrees = json.loads(chemin.read_text(encoding="utf-8"))
    n = 0
    for e in reversed(entrees):
        if e.get("type") == "rmdir":  # journaux antérieurs
            Path(e["path"]).mkdir(parents=True, exist_ok=True)
            n += 1
        else:
            de, vers = Path(e["de"]), Path(e["vers"])
            if de.exists() and not vers.exists():
                vers.parent.mkdir(parents=True, exist_ok=True)
                shutil.move(str(de), str(vers))
                n += 1
    return n
