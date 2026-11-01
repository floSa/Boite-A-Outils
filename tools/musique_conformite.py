"""Vérification de la conformité des albums et détection des téléchargements incomplets (extraits de 30s).

Règles de conformité :
1. Règle des 30 secondes (extraits / previews) :
   - Vérifie la durée de chaque piste audio via `mutagen`.
   - Si >= 70% des pistes d'un album ont une durée <= 35 secondes (ou si toutes les pistes
     font <= 35 secondes), l'album est considéré non conforme (preview Qobuz incomplète).
2. Intégrité des fichiers audio :
   - Détecte tout fichier audio illisible ou corrompu.
3. Isolation / Quarantaine :
   - Isole les albums ou fichiers non conformes dans un répertoire de quarantaine
     sans jamais les transférer sur le NAS.
"""

from __future__ import annotations

import os
import shutil
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

import mutagen

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

SEUIL_DUREE_EXTRAIT_SEC = 35.0
SEUIL_RATIO_EXTRAIT = 0.70
NOM_DOSSIER_QUARANTAINE_DEFAUT = "_quarantaine_incomplets"


@dataclass
class PisteAudioInfo:
    """Informations d'intégrité et de durée d'une piste audio."""

    chemin: Path
    nom: str
    duree_sec: float = 0.0
    est_extrait: bool = False
    est_corrompu: bool = False
    erreur: Optional[str] = None


@dataclass
class BilanAlbum:
    """Bilan de conformité pour un album ou un dossier contenant des pistes."""

    artiste: str
    album: str
    chemin: Path
    pistes: list[PisteAudioInfo] = field(default_factory=list)
    est_conforme: bool = True
    motif_non_conforme: str = ""

    @property
    def nb_pistes(self) -> int:
        return len(self.pistes)

    @property
    def nb_extraits(self) -> int:
        return sum(1 for p in self.pistes if p.est_extrait)

    @property
    def nb_corrompues(self) -> int:
        return sum(1 for p in self.pistes if p.est_corrompu)

    @property
    def ratio_extraits(self) -> float:
        return (self.nb_extraits / self.nb_pistes) if self.nb_pistes > 0 else 0.0


@dataclass
class BilanConformite:
    """Bilan global de conformité pour une bibliothèque ou un dossier source."""

    racine: Path
    albums_conformes: list[BilanAlbum] = field(default_factory=list)
    albums_non_conformes: list[BilanAlbum] = field(default_factory=list)

    @property
    def total_albums(self) -> int:
        return len(self.albums_conformes) + len(self.albums_non_conformes)

    @property
    def total_pistes_extraits(self) -> int:
        return sum(a.nb_extraits for a in self.albums_non_conformes)

    @property
    def total_pistes_corrompues(self) -> int:
        return sum(
            a.nb_corrompues for a in self.albums_conformes + self.albums_non_conformes
        )


def analyser_piste(
    chemin: Path, seuil_duree: float = SEUIL_DUREE_EXTRAIT_SEC
) -> PisteAudioInfo:
    """Lit les métadonnées et la durée d'une piste audio via mutagen.

    :param chemin: Chemin vers le fichier audio.
    :param seuil_duree: Seuil en secondes en dessous duquel une piste est un extrait.
    :return: PisteAudioInfo avec durée et indicateurs de validité.
    """
    try:
        audio = mutagen.File(chemin)
        if audio is None or audio.info is None:
            return PisteAudioInfo(
                chemin=chemin,
                nom=chemin.name,
                est_corrompu=True,
                erreur="En-tête audio illisible ou format non reconnu.",
            )

        duree = getattr(audio.info, "length", 0.0)
        est_extrait = duree <= seuil_duree

        return PisteAudioInfo(
            chemin=chemin,
            nom=chemin.name,
            duree_sec=duree,
            est_extrait=est_extrait,
            est_corrompu=False,
        )
    except Exception as e:
        return PisteAudioInfo(
            chemin=chemin,
            nom=chemin.name,
            est_corrompu=True,
            erreur=str(e),
        )


def verifier_album(
    dossier: Path,
    artiste: str = "",
    seuil_duree: float = SEUIL_DUREE_EXTRAIT_SEC,
    seuil_ratio: float = SEUIL_RATIO_EXTRAIT,
) -> Optional[BilanAlbum]:
    """Vérifie la conformité d'un dossier d'album.

    :param dossier: Chemin du dossier album.
    :param artiste: Nom de l'artiste parent (optionnel).
    :param seuil_duree: Seuil de détection d'extrait (secondes).
    :param seuil_ratio: Ratio d'extraits pour déclarer l'album non conforme.
    :return: BilanAlbum si le dossier contient de l'audio, None sinon.
    """
    fichiers_audio = [
        f
        for f in dossier.iterdir()
        if f.is_file()
        and f.suffix.lower() in EXT_AUDIO
        and not f.name.startswith((".", "_"))
    ]

    if not fichiers_audio:
        return None

    if not artiste:
        artiste = dossier.parent.name if dossier.parent != dossier else "Inconnu"

    pistes = [analyser_piste(f, seuil_duree) for f in sorted(fichiers_audio)]
    nb_total = len(pistes)
    nb_extraits = sum(1 for p in pistes if p.est_extrait)
    nb_corrompus = sum(1 for p in pistes if p.est_corrompu)

    ratio_extraits = (nb_extraits / nb_total) if nb_total > 0 else 0.0

    est_conforme = True
    motif = ""

    if nb_corrompus > 0:
        est_conforme = False
        motif = f"{nb_corrompus} piste(s) audio corrompue(s) ou illisible(s)."
    elif (ratio_extraits >= seuil_ratio) or (nb_extraits == nb_total and nb_total > 0):
        est_conforme = False
        motif = f"Album composé d'extraits de preview ({nb_extraits}/{nb_total} pistes <= {seuil_duree}s, ratio {ratio_extraits:.0%})."

    return BilanAlbum(
        artiste=artiste,
        album=dossier.name,
        chemin=dossier,
        pistes=pistes,
        est_conforme=est_conforme,
        motif_non_conforme=motif,
    )


def analyser_conformite_bibliotheque(
    racine: str | Path,
    seuil_duree: float = SEUIL_DUREE_EXTRAIT_SEC,
    seuil_ratio: float = SEUIL_RATIO_EXTRAIT,
    progress: Optional[Callable[[int, int], None]] = None,
) -> BilanConformite:
    """Parcourt l'arborescence (racine / Artiste / Album) et évalue la conformité de chaque album.

    :param racine: Racine de la bibliothèque.
    :param seuil_duree: Durée max considérée comme un extrait.
    :param seuil_ratio: Ratio déclenchant la mise en quarantaine.
    :param progress: Callback d'avancement (traités, total).
    :return: BilanConformite global.
    """
    base = Path(racine)
    bilan = BilanConformite(racine=base)

    if not base.is_dir():
        return bilan

    # Lister les artistes (dossiers de premier niveau, ignorant les cachés)
    artistes = [
        d for d in base.iterdir() if d.is_dir() and not d.name.startswith((".", "_"))
    ]

    total = len(artistes)
    for i, art_dir in enumerate(sorted(artistes, key=lambda p: p.name.lower()), 1):
        if progress:
            progress(i, total)

        # Chercher les albums sous l'artiste
        for item in art_dir.iterdir():
            if item.is_dir() and not item.name.startswith((".", "_")):
                b_album = verifier_album(
                    item,
                    artiste=art_dir.name,
                    seuil_duree=seuil_duree,
                    seuil_ratio=seuil_ratio,
                )
                if b_album:
                    if b_album.est_conforme:
                        bilan.albums_conformes.append(b_album)
                    else:
                        bilan.albums_non_conformes.append(b_album)

    return bilan


def isoler_quarantaine(
    bilan: BilanConformite,
    destination_quarantaine: Optional[str | Path] = None,
) -> list[tuple[Path, Path]]:
    """Déplace tous les albums non conformes dans le dossier de quarantaine.

    Préserve l'arborescence Artiste/Album pour faciliter la réacquisition ultérieure.

    :param bilan: Bilan de conformité contenant les albums non conformes.
    :param destination_quarantaine: Dossier cible (défaut : <racine>/_quarantaine_incomplets).
    :return: Liste des déplacements effectués [(source, destination), ...].
    """
    if destination_quarantaine is None:
        destination = bilan.racine / NOM_DOSSIER_QUARANTAINE_DEFAUT
    else:
        destination = Path(destination_quarantaine)

    destination.mkdir(parents=True, exist_ok=True)
    deplacements: list[tuple[Path, Path]] = []

    for album in bilan.albums_non_conformes:
        dest_artiste = destination / album.artiste
        dest_album = dest_artiste / album.chemin.name

        dest_artiste.mkdir(parents=True, exist_ok=True)
        # Si un album de même nom existe déjà dans la quarantaine, ajouter un suffixe
        if dest_album.exists():
            compteur = 2
            while (dest_artiste / f"{album.chemin.name} ({compteur})").exists():
                compteur += 1
            dest_album = dest_artiste / f"{album.chemin.name} ({compteur})"

        shutil.move(str(album.chemin), str(dest_album))
        deplacements.append((album.chemin, dest_album))

        # Si le dossier artiste d'origine est devenu vide, le supprimer
        parent_artiste = album.chemin.parent
        try:
            if parent_artiste.exists() and not any(parent_artiste.iterdir()):
                parent_artiste.rmdir()
        except OSError:
            pass

    return deplacements
