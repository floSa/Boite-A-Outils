"""Normaliser les noms d'une bibliothèque musicale ``Artiste\\Album\\Titres``.

Typiquement après un import dont les dossiers et fichiers portent des métadonnées
techniques parasites. L'outil travaille **exclusivement** sur les noms de dossiers
et de fichiers — il ne lit ni n'écrit aucun tag ID3/Vorbis.

Deux temps, à l'image du reste de la boîte à outils :

- ``previsualiser_nettoyage(racine)`` calcule ce qui sera modifié, sans rien écrire
  (c'est l'« audit »).
- ``appliquer(plan, racine)`` exécute et écrit un journal d'annulation.

Deux règles sont couvertes ici (la 3ᵉ, le regroupement des « singles », est
assurée par l'outil dédié :mod:`tools.musique`) :

Règle 1 — nom de dossier d'album
    Supprime, **en fin de nom** et de façon répétée jusqu'à stabilité, les suffixes
    techniques ``(Clean)``/``(Explicit)``, ``[UPC…]`` et ``{…}``. Une année finale
    (``(2023)`` ou ``[2023]``) n'est retirée que si l'un de ces suffixes la suivait
    (``Derealised (2023) (Clean) [UPC…]`` → ``Derealised``) ; une année **seule**
    est conservée (``Nom (2023)`` reste ``Nom (2023)``, ``Nom [Disk 1]`` reste
    ``Nom [Disk 1]``). Les parenthèses porteuses de sens (``(Deluxe)``,
    ``(Bande Originale du Film)``…) et internes (``Génération(s)``) sont préservées.

Règle 2 — nom de fichier audio
    ``01. Artiste - Titre.flac`` → ``01 - Titre.flac``. Le découpage artiste/titre
    se fait sur le **premier** ``" - "`` seulement, pour ne pas casser un titre tel
    que ``07. Clothilde - 102 - 103`` → ``07 - 102 - 103``. Un fichier déjà au
    format ``01 - Titre`` n'est pas reconnu (tiret, pas point) : l'outil est donc
    idempotent.

Invariants : aucune perte de fichier (uniquement des renommages), aucun écrasement
(collision → suffixe `` (2)``, `` (3)``…), dossiers ``.``/``_`` ignorés à tous les
niveaux.
"""

from __future__ import annotations

import json
import os
import re
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

# Rapporte l'avancement d'un scan : (artistes traités, total artistes).
Progression = Callable[[int, int], None]

from tools.files import Renommage

AUDIO_EXT = {".flac", ".mp3", ".m4a", ".wav", ".ogg", ".opus", ".aiff", ".wma", ".alac"}
NOM_JOURNAL_NETTOYAGE = ".nettoyage_undo.json"
NOM_DOSSIER_SINGLES = "Singles"

# Caractères interdits par le système de fichiers → remplacés par « _ ».
_CARACTERES_INTERDITS = re.compile(r'[<>:"/\\|?*\x00-\x1f]')

# Règle 1 — suffixes techniques reconnus uniquement en fin de nom.
# « Durs » : toujours retirés (ce sont clairement des métadonnées parasites).
_SUFFIXES_DURS = [
    re.compile(r"\((?:clean|explicit)\)\s*$", re.I),  # (Clean) / (Explicit)
    re.compile(r"\[UPC[^\]]*\]\s*$", re.I),  # [UPC5060525433962]
    re.compile(r"\{[^}]*\}\s*$"),  # {WEB}
]
# Une année en fin — (2023) ou [2023] — n'est retirée QUE si un suffixe dur a
# déjà été retiré à sa droite (ex. « (2023) (Clean) [UPC…] »). Une année SEULE
# est conservée : « Nom (2023) » reste « Nom (2023) ».
_ANNEE_FINALE = re.compile(r"(?:\((?:19|20)\d{2}\)|\[(?:19|20)\d{2}\])\s*$")

# Règle 2 : « <num>. <reste> » ou « <num>) <reste> » (mais pas « <num> - … »).
_PISTE = re.compile(r"^\s*(\d{1,3})\s*[.)]\s*(.+)$")


def _assainir(nom: str) -> str:
    """Remplace les caractères interdits par « _ » (noms produits uniquement)."""
    return _CARACTERES_INTERDITS.sub("_", nom)


def nettoyer_nom_album(nom: str) -> str:
    """Applique la règle 1 : retire les suffixes techniques de fin, jusqu'à stabilité.

    - ``(Clean)``, ``(Explicit)``, ``[UPC…]``, ``{…}`` : toujours retirés.
    - Une année finale ``(2023)`` / ``[2023]`` n'est retirée que si un suffixe dur
      la suivait (``Derealised (2023) (Clean) [UPC…]`` → ``Derealised``). Seule,
      elle est conservée (``Nom (2023)`` reste ``Nom (2023)``).
    - Tout le reste est préservé : ``[Disk 1]``, ``(Deluxe)``,
      ``(Bande Originale du Film)``, parenthèses internes…
    """
    resultat = nom.rstrip()
    dur_retire = False
    while True:
        avant = resultat
        for motif in _SUFFIXES_DURS:
            nouveau = motif.sub("", resultat).rstrip()
            if nouveau != resultat:
                resultat = nouveau
                dur_retire = True
                break
        if resultat != avant:
            continue  # un suffixe dur retiré → on recommence
        # Aucun suffixe dur ce tour : année conditionnelle si un dur a précédé.
        if dur_retire:
            nouveau = _ANNEE_FINALE.sub("", resultat).rstrip()
            if nouveau != resultat:
                resultat = nouveau
                continue
        break
    # Si le nom était entièrement « technique » (ex. « {Awayland} »), on ne renvoie
    # jamais un nom vide : mieux vaut le laisser tel quel que créer un artefact.
    return resultat or nom.rstrip()


def renommer_piste(stem: str) -> str | None:
    """Applique la règle 2 sur un nom de fichier **sans extension**.

    :return: le nouveau nom (sans extension), ou ``None`` si le fichier n'est pas
        au format « numéro. reste » (donc à ne pas toucher — idempotence).
    """
    m = _PISTE.match(stem)
    if not m:
        return None
    num, reste = m.group(1), m.group(2)
    # Couper sur le PREMIER « - » seulement : la gauche (artiste) est jetée.
    titre = reste.split(" - ", 1)[1] if " - " in reste else reste
    return f"{int(num):02d} - {titre.strip()}"


@dataclass
class PlanNettoyage:
    albums: list[Renommage] = field(default_factory=list)  # dossiers d'album (règle 1)
    pistes: list[Renommage] = field(default_factory=list)  # fichiers audio (règle 2)

    def __bool__(self) -> bool:
        return bool(self.albums or self.pistes)


def _sous_dossiers_visibles(chemin: Path) -> list[Path]:
    """Sous-dossiers directs, hors dossiers ``.``/``_``.

    Via ``os.scandir`` (le type est mis en cache par le noyau : bien moins d'appels
    ``stat`` qu'``iterdir`` + ``is_dir``, ce qui compte énormément sur un partage réseau).
    """
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


def _fichiers_audio(album: Path):
    """Itère les fichiers audio d'un album (récursif : CD 01 / CD 02).

    Via ``os.walk`` : on ne lit que les **noms** (aucun ``stat`` par fichier). Les
    sous-dossiers ``.``/``_`` sont ignorés.
    """
    for dirpath, dirnames, filenames in os.walk(album):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for nom in filenames:
            stem, ext = os.path.splitext(nom)
            if ext.lower() in AUDIO_EXT:
                yield Path(dirpath) / nom, stem, ext


def previsualiser_nettoyage(
    racine: str | Path, *, progress: Progression | None = None
) -> PlanNettoyage:
    """Calcule les renommages des règles 1 et 2 sans rien modifier (l'« audit »).

    :param progress: rappelé après chaque artiste avec ``(traités, total)``.
    """
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    plan = PlanNettoyage()
    artistes = _sous_dossiers_visibles(base)
    total = len(artistes)
    for i, artiste in enumerate(artistes, 1):
        for album in _sous_dossiers_visibles(artiste):
            if album.name.lower() == NOM_DOSSIER_SINGLES.lower():
                continue
            # Règle 2 — fichiers audio (récursif pour les albums multi-disques).
            for f, stem, ext in _fichiers_audio(album):
                nouveau_stem = renommer_piste(stem)
                if nouveau_stem is None:
                    continue
                cible = f.with_name(_assainir(nouveau_stem) + ext)
                if cible != f:
                    plan.pistes.append(Renommage(ancien=f, nouveau=cible))
            # Règle 1 — nom du dossier d'album.
            nouveau_nom = _assainir(nettoyer_nom_album(album.name))
            if nouveau_nom and nouveau_nom != album.name:
                plan.albums.append(
                    Renommage(ancien=album, nouveau=album.with_name(nouveau_nom))
                )
        if progress:
            progress(i, total)
    return plan


def _libre(cible: Path, reserves: set[str]) -> Path:
    """Chemin cible non utilisé (ni sur disque, ni réservé) ; suffixe (2), (3)…"""
    if str(cible).lower() not in reserves and not cible.exists():
        reserves.add(str(cible).lower())
        return cible
    tige, ext = cible.stem, cible.suffix
    i = 2
    while True:
        candidat = cible.with_name(f"{tige} ({i}){ext}")
        if str(candidat).lower() not in reserves and not candidat.exists():
            reserves.add(str(candidat).lower())
            return candidat
        i += 1


@dataclass
class ResultatNettoyage:
    journal: Path
    nb_renommes: int
    erreurs: list[str] = field(default_factory=list)


def appliquer(plan: PlanNettoyage, racine: str | Path) -> ResultatNettoyage:
    """Exécute le plan et écrit un journal d'annulation.

    Les fichiers sont renommés **avant** les dossiers d'album : ainsi le renommage
    d'un dossier déplace des fichiers déjà à leur nom final, et les chemins
    calculés restent valides.

    Résilient au réseau : si un renommage échoue (fichier verrouillé, chemin trop
    long, permission), l'erreur est collectée et le traitement continue — jamais
    d'interruption à mi-parcours. Aucun fichier n'est supprimé : uniquement des
    renommages. Le journal (ce qui a réellement bougé) permet l'annulation.
    """
    reserves: set[str] = set()
    journal: list[dict[str, str]] = []
    erreurs: list[str] = []
    for lot in (plan.pistes, plan.albums):
        for r in lot:
            if not r.ancien.exists():
                continue
            cible = _libre(r.nouveau, reserves)
            try:
                cible.parent.mkdir(parents=True, exist_ok=True)
                r.ancien.rename(cible)
            except OSError as e:
                erreurs.append(f"{r.ancien} : {e}")
                continue
            journal.append({"de": str(cible), "vers": str(r.ancien)})

    chemin = Path(racine) / NOM_JOURNAL_NETTOYAGE
    try:
        chemin.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        erreurs.append(f"Journal d'annulation non écrit ({chemin}) : {e}")
    return ResultatNettoyage(journal=chemin, nb_renommes=len(journal), erreurs=erreurs)


def annuler(racine: str | Path) -> int:
    """Restaure les noms d'origine depuis le journal. Retourne le nombre d'actions annulées.

    Parcours en ordre inverse : les dossiers d'album reviennent à leur nom avant
    les fichiers qu'ils contiennent.
    """
    chemin = Path(racine) / NOM_JOURNAL_NETTOYAGE
    if not chemin.is_file():
        raise FileNotFoundError(f"Aucun journal de nettoyage dans {racine}")

    entrees = json.loads(chemin.read_text(encoding="utf-8"))
    n = 0
    for e in reversed(entrees):
        de, vers = Path(e["de"]), Path(e["vers"])
        if de.exists() and not vers.exists():
            vers.parent.mkdir(parents=True, exist_ok=True)
            de.rename(vers)
            n += 1
    return n
