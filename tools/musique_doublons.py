"""Outils de détection et suppression des doublons dans une bibliothèque musicale.

Couvre trois types de doublons :
1. Singles déjà présents dans un album du même artiste.
2. Pistes audio en double au sein d'un même album (doublons de fichiers, collision (2)).
3. Albums similaires d'un même artiste (ex: version Standard vs version Deluxe).
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import unicodedata
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
NOM_DOSSIER_SINGLES = "Singles"
NOM_CORBEILLE_DOUBLONS = "_doublons_a_supprimer"


def chemin_journal_doublons(racine: str | Path) -> Path:
    """Renvoie le chemin du journal d'annulation stocké côté application."""
    return get_chemin_journal(racine, "doublons")

_RE_NUM_PISTE = re.compile(r"^\s*(?:\d{1,3}\s*[-.)]\s*|0\d{1,2}\s+)")
_RE_SUFFIXE_COLLISION = re.compile(r"\s*\(\d+\)$")

Progression = Callable[[int, int], None]


def normaliser_titre(titre: str) -> str:
    """Normalise un titre pour comparaison insensible à la casse, aux accents et à la ponctuation.

    Retire les numéros de piste en tête, les suffixes de collision `(2)`, les préfixes `Artiste - `,
    puis convertit en minuscules sans accents.
    """
    t = _RE_NUM_PISTE.sub("", titre).strip()
    t = _RE_SUFFIXE_COLLISION.sub("", t).strip()
    if " - " in t:
        t = t.split(" - ", 1)[1].strip()
    t = unicodedata.normalize("NFKD", t).encode("ascii", "ignore").decode("utf-8")
    t = re.sub(r"[^\w\s]", "", t)
    return " ".join(t.lower().split())


MOTS_CLES_EDITIONS = (
    r"super\s+deluxe(?:\s+edition|\s+version)?",
    r"deluxe(?:\s+edition|\s+version)?",
    r"extended(?:\s+edition|\s+version|\s+cut)?",
    r"expanded(?:\s+edition|\s+version)?",
    r"special(?:\s+edition|\s+version)?",
    r"limited(?:\s+edition|\s+version)?",
    r"collector\'?s?(?:\s+edition)?",
    r"tour\s+edition",
    r"(?:\d+th\s+)?anniversary(?:\s+edition)?",
    r"remaster(?:ed|is[eé]e?)?(?:\s+\d{4})?",
    r"bonus\s+tracks?(?:\s+edition)?",
    r"complete\s+edition",
    r"reissue",
    r"edition\s+deluxe",
    r"version\s+longue",
    r"instrumental(?:\s+version)?",
    r"acoustic(?:\s+version)?",
    r"live\s+edition",
    r"standard(?:\s+edition|\s+version)?",
    r"definitive(?:\s+edition)?",
    r"international(?:\s+edition)?",
)

_PATTERN_SUFFIXE_EDITION = re.compile(
    r"(?:\s*[-–—:|]\s*|\s+)(?:" + "|".join(MOTS_CLES_EDITIONS) + r")\s*$",
    re.IGNORECASE,
)


def nom_album_base(nom: str) -> str:
    """Extrait le nom de base d'un album en retirant crochets, parenthèses et mentions d'édition.

    Préserve le nom complet si celui-ci n'est constitué que du mot-clé (ex: l'album 'Deluxe'
    du groupe Deluxe n'est pas vidé).
    """
    original = nom.strip()

    # 1. Supprimer le contenu entre crochets [...], parenthèses (...) ou accolades {...}
    sans_crochets = re.sub(r"[\(\[\{][^\)\]\}]*[\)\]\}]", "", original).strip()

    # Si tout a été supprimé (ex: album nommé '(Deluxe)' ou '[Disk 1]'), préserver le contenu sans les délimiteurs
    base = (
        sans_crochets
        if sans_crochets
        else re.sub(r"^[(\[{]+|[)\]}]+$", "", original).strip()
    )
    base = re.sub(r"\s*[-–—:|]\s*$", "", base).strip()

    # 2. Supprimer les suffixes d'édition (Deluxe, Extended, etc.) en fin de chaîne ou après un séparateur
    while True:
        sans_suffixe = _PATTERN_SUFFIXE_EDITION.sub("", base).strip()
        sans_suffixe = re.sub(r"\s*[-–—:|]\s*$", "", sans_suffixe).strip()
        if sans_suffixe and sans_suffixe != base:
            base = sans_suffixe
        else:
            break

    return base or original


def _hash_fichier(path: Path, taille_bloc: int = 1 << 20) -> str:
    """Calcule l'empreinte SHA-1 d'un fichier."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while bloc := f.read(taille_bloc):
            h.update(bloc)
    return h.hexdigest()


def _sous_dossiers_visibles(chemin: Path) -> list[Path]:
    """Liste les sous-dossiers directs visibles (hors `.` et `_`)."""
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


def _fichiers_audio_album(album_dir: Path) -> list[Path]:
    """Itère rapidement tous les fichiers audio d'un album via os.walk."""
    fichiers: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(album_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for nom in filenames:
            ext = os.path.splitext(nom)[1].lower()
            if ext in EXT_AUDIO:
                fichiers.append(Path(dirpath) / nom)
    return sorted(fichiers)


# =============================================================================
# 1. Singles déjà présents dans un album
# =============================================================================


@dataclass
class DoublonSingle:
    artiste: str
    single_path: Path
    album_nom: str
    album_track_path: Path
    raison: str


def detecter_singles_en_album(
    racine: str | Path, *, progress: Progression | None = None
) -> list[DoublonSingle]:
    """Identifie les singles d'un artiste qui sont déjà présents dans l'un de ses albums."""
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    doublons: list[DoublonSingle] = []
    artistes = _sous_dossiers_visibles(base)
    total = len(artistes)

    for i, artiste in enumerate(artistes, 1):
        singles_dir = artiste / NOM_DOSSIER_SINGLES
        if singles_dir.is_dir():
            # Indexer tous les titres des albums de l'artiste
            titres_albums: dict[str, tuple[str, Path]] = {}
            tailles_albums: dict[int, list[tuple[str, Path]]] = {}

            for album in _sous_dossiers_visibles(artiste):
                if album.name.lower() == NOM_DOSSIER_SINGLES.lower():
                    continue
                for f in _fichiers_audio_album(album):
                    cle = normaliser_titre(f.stem)
                    if cle and cle not in titres_albums:
                        titres_albums[cle] = (album.name, f)
                    try:
                        sz = f.stat().st_size
                        tailles_albums.setdefault(sz, []).append((album.name, f))
                    except OSError:
                        pass

            # Vérifier chaque single
            for s in _fichiers_audio_album(singles_dir):
                s_cle = normaliser_titre(s.stem)
                trouve = False

                # 1. Correspondance par titre normalisé
                if s_cle in titres_albums:
                    alb_nom, alb_track = titres_albums[s_cle]
                    doublons.append(
                        DoublonSingle(
                            artiste=artiste.name,
                            single_path=s,
                            album_nom=alb_nom,
                            album_track_path=alb_track,
                            raison="Même titre présent dans l'album",
                        )
                    )
                    trouve = True

                # 2. Correspondance exacte par taille + hash si non trouvé par titre
                if not trouve:
                    try:
                        s_sz = s.stat().st_size
                        if s_sz in tailles_albums:
                            s_hash = _hash_fichier(s)
                            for alb_nom, alb_track in tailles_albums[s_sz]:
                                if _hash_fichier(alb_track) == s_hash:
                                    doublons.append(
                                        DoublonSingle(
                                            artiste=artiste.name,
                                            single_path=s,
                                            album_nom=alb_nom,
                                            album_track_path=alb_track,
                                            raison="Fichier identique (empreinte SHA-1)",
                                        )
                                    )
                                    break
                    except OSError:
                        pass

        if progress:
            progress(i, total)

    return doublons


# =============================================================================
# 2. Pistes audio en double au sein d'un même album
# =============================================================================


@dataclass
class DoublonPiste:
    artiste: str
    album: str
    piste_a_garder: Path
    piste_en_trop: Path
    raison: str


def detecter_pistes_en_double(
    racine: str | Path, *, progress: Progression | None = None
) -> list[DoublonPiste]:
    """Identifie les fichiers audio en double au sein de chaque dossier d'album."""
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    doublons: list[DoublonPiste] = []
    artistes = _sous_dossiers_visibles(base)
    total = len(artistes)

    for i, artiste in enumerate(artistes, 1):
        for album in _sous_dossiers_visibles(artiste):
            # Parcourir chaque répertoire de l'album (album direct ou sous-dossier CD 01)
            for dirpath, dirnames, filenames in os.walk(album):
                dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
                audios: list[Path] = [
                    Path(dirpath) / n
                    for n in filenames
                    if os.path.splitext(n)[1].lower() in EXT_AUDIO
                ]
                if len(audios) < 2:
                    continue

                # 1. Vérification par contenu exact (taille identique puis SHA-1)
                par_taille: dict[int, list[Path]] = {}
                for f in audios:
                    try:
                        par_taille.setdefault(f.stat().st_size, []).append(f)
                    except OSError:
                        pass

                traites_par_hash: set[Path] = set()
                for sz, candidats in par_taille.items():
                    if len(candidats) > 1:
                        par_hash: dict[str, list[Path]] = {}
                        for c in candidats:
                            try:
                                par_hash.setdefault(_hash_fichier(c), []).append(c)
                            except OSError:
                                pass
                        for h, groupe in par_hash.items():
                            if len(groupe) > 1:
                                # Le premier sans suffixe (2) est gardé, les autres marqués en trop
                                groupe.sort(
                                    key=lambda p: (
                                        bool(_RE_SUFFIXE_COLLISION.search(p.stem)),
                                        len(p.name),
                                        p.name,
                                    )
                                )
                                original = groupe[0]
                                for clone in groupe[1:]:
                                    doublons.append(
                                        DoublonPiste(
                                            artiste=artiste.name,
                                            album=album.name,
                                            piste_a_garder=original,
                                            piste_en_trop=clone,
                                            raison="Contenu audio identique (SHA-1)",
                                        )
                                    )
                                    traites_par_hash.add(clone)

                # 2. Vérification par nom / titre normalisé dans le même dossier
                par_titre: dict[str, list[Path]] = {}
                for f in audios:
                    if f in traites_par_hash:
                        continue
                    norm = normaliser_titre(f.stem)
                    if norm:
                        par_titre.setdefault(norm, []).append(f)

                for norm, groupe in par_titre.items():
                    if len(groupe) > 1:
                        # Si les morceaux ont des numéros de piste distincts et sans collision (2),
                        # ce sont des mouvements ou parties différents (ex: 07 - Beginning vs 09 - Beginning)
                        def _num_piste(p: Path) -> str:
                            m = _RE_NUM_PISTE.match(p.stem)
                            if m:
                                digits = re.search(r"\d+", m.group(0))
                                return str(int(digits.group(0))) if digits else ""
                            return ""

                        nums = {_num_piste(p) for p in groupe}
                        a_collision = any(_RE_SUFFIXE_COLLISION.search(p.stem) for p in groupe)
                        if len(nums) > 1 and "" not in nums and not a_collision:
                            continue

                        # Priorité : FLAC > autre, sans suffixe (2) > avec, plus gros > plus petit
                        def _cle_priorite(p: Path) -> tuple[int, int, int]:
                            est_flac = 1 if p.suffix.lower() == ".flac" else 0
                            a_collision = (
                                1 if _RE_SUFFIXE_COLLISION.search(p.stem) else 0
                            )
                            try:
                                taille = p.stat().st_size
                            except OSError:
                                taille = 0
                            return (-est_flac, a_collision, -taille)

                        groupe.sort(key=_cle_priorite)
                        garde = groupe[0]
                        for trop in groupe[1:]:
                            doublons.append(
                                DoublonPiste(
                                    artiste=artiste.name,
                                    album=album.name,
                                    piste_a_garder=garde,
                                    piste_en_trop=trop,
                                    raison="Même titre dans l'album (ex: doublon renommé)",
                                )
                            )

        if progress:
            progress(i, total)

    return doublons


# =============================================================================
# 3. Albums similaires / Versions Deluxe d'un même artiste
# =============================================================================


@dataclass
class PaireAlbumsSimilaires:
    artiste: str
    album_1: Path
    album_2: Path
    similarite: float
    nb_titres_1: int
    nb_titres_2: int
    titres_communs: list[str]
    titres_uniques_1: list[str]
    titres_uniques_2: list[str]
    taille_1: int
    taille_2: int
    meme_nom_base: bool = False
    nom_base: str = ""


def detecter_albums_similaires(
    racine: str | Path,
    *,
    seuil_similarite: float = 0.70,
    progress: Progression | None = None,
) -> list[PaireAlbumsSimilaires]:
    """Détecte les paires d'albums d'un même artiste partageant une forte proportion de titres."""
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    paires: list[PaireAlbumsSimilaires] = []
    artistes = _sous_dossiers_visibles(base)
    total = len(artistes)

    for idx, artiste in enumerate(artistes, 1):
        albums = [
            a
            for a in _sous_dossiers_visibles(artiste)
            if a.name.lower() != NOM_DOSSIER_SINGLES.lower()
        ]
        if len(albums) >= 2:
            # Récolter les métadonnées de chaque album
            infos_albums = []
            for alb in albums:
                fichiers = _fichiers_audio_album(alb)
                if not fichiers:
                    continue
                titres_map: dict[str, str] = {}
                taille = 0
                for f in fichiers:
                    norm = normaliser_titre(f.stem)
                    if norm:
                        titres_map[norm] = f.name
                    try:
                        taille += f.stat().st_size
                    except OSError:
                        pass
                infos_albums.append((alb, titres_map, taille))

            # Comparer toutes les paires d'albums
            for i in range(len(infos_albums)):
                for j in range(i + 1, len(infos_albums)):
                    alb_1, map_1, sz_1 = infos_albums[i]
                    alb_2, map_2, sz_2 = infos_albums[j]

                    cles_1 = set(map_1.keys())
                    cles_2 = set(map_2.keys())
                    if not cles_1 or not cles_2:
                        continue

                    communes = cles_1 & cles_2
                    min_taille = min(len(cles_1), len(cles_2))
                    if min_taille == 0:
                        continue

                    ratio = len(communes) / min_taille

                    # Vérifier si les noms d'albums nettoyés (sans crochets/parenthèses/deluxe) sont identiques
                    base_1 = nom_album_base(alb_1.name)
                    base_2 = nom_album_base(alb_2.name)
                    cle_base_1 = normaliser_titre(base_1)
                    cle_base_2 = normaliser_titre(base_2)
                    meme_nom_base = bool(cle_base_1 and cle_base_1 == cle_base_2)

                    # Si même nom d'album de base (ex: Standard vs Deluxe), on détecte dès 35% de titres partagés,
                    # sinon on applique le seuil_similarite configuré.
                    if (meme_nom_base and ratio >= 0.35) or (ratio >= seuil_similarite):
                        paires.append(
                            PaireAlbumsSimilaires(
                                artiste=artiste.name,
                                album_1=alb_1,
                                album_2=alb_2,
                                similarite=ratio,
                                nb_titres_1=len(cles_1),
                                nb_titres_2=len(cles_2),
                                titres_communs=sorted(map_1[c] for c in communes),
                                titres_uniques_1=sorted(
                                    map_1[c] for c in (cles_1 - cles_2)
                                ),
                                titres_uniques_2=sorted(
                                    map_2[c] for c in (cles_2 - cles_1)
                                ),
                                taille_1=sz_1,
                                taille_2=sz_2,
                                meme_nom_base=meme_nom_base,
                                nom_base=base_1 if meme_nom_base else "",
                            )
                        )

        if progress:
            progress(idx, total)

    return sorted(paires, key=lambda p: p.similarite, reverse=True)


# =============================================================================
# Traitement des doublons (Corbeille & Annulation)
# =============================================================================


def _deplacer_vers_corbeille(
    source: Path, racine: Path, reserves: set[str], journal: list[dict[str, str]]
) -> Path:
    """Déplace un fichier ou un dossier dans _doublons_a_supprimer/ avec nommage unique."""
    corbeille = racine / NOM_CORBEILLE_DOUBLONS
    rel = source.relative_to(racine)
    cible = corbeille / rel
    cible.parent.mkdir(parents=True, exist_ok=True)

    dest = cible
    if str(dest).lower() in reserves or dest.exists():
        i = 2
        while True:
            if source.is_file():
                dest = cible.with_name(f"{cible.stem} ({i}){cible.suffix}")
            else:
                dest = cible.with_name(f"{cible.name} ({i})")
            if str(dest).lower() not in reserves and not dest.exists():
                break
            i += 1

    reserves.add(str(dest).lower())
    shutil.move(str(source), str(dest))
    journal.append({"type": "move", "de": str(dest), "vers": str(source)})
    return dest


def supprimer_fichiers(
    chemins: list[Path],
    racine: str | Path,
    *,
    corbeille: bool = True,
) -> int:
    """Supprime ou met en corbeille une liste de fichiers audio doublons."""
    base = Path(racine)
    journal_path = chemin_journal_doublons(base)
    journal: list[dict[str, str]] = []
    if journal_path.is_file():
        try:
            journal = json.loads(journal_path.read_text(encoding="utf-8"))
        except Exception:
            journal = []

    reserves: set[str] = set()
    nb = 0
    for f in chemins:
        if not f.exists():
            continue
        try:
            if corbeille:
                _deplacer_vers_corbeille(f, base, reserves, journal)
            else:
                if f.is_file():
                    try:
                        os.chmod(f, stat.S_IWRITE)
                    except OSError:
                        pass
                    f.unlink()
                elif f.is_dir():
                    shutil.rmtree(f, ignore_errors=True)
            nb += 1
        except OSError:
            continue

        # Si le fichier supprimé rend son dossier d'album vide (hors junk), supprimer l'album vide
        parent_album = f.parent
        if parent_album.exists() and parent_album != base:
            # Nettoyer les fichiers junk résiduels
            for junk in parent_album.iterdir():
                if junk.is_file() and junk.name.lower() in ("thumbs.db", ".ds_store", "desktop.ini"):
                    try:
                        junk.unlink(missing_ok=True)
                    except OSError:
                        pass
            if not list(parent_album.iterdir()):
                try:
                    parent_album.rmdir()
                except OSError:
                    pass
            # Et si l'artiste devient vide à son tour
            parent_artiste = parent_album.parent
            if parent_artiste.exists() and parent_artiste != base:
                for junk in parent_artiste.iterdir():
                    if junk.is_file() and junk.name.lower() in ("thumbs.db", ".ds_store", "desktop.ini"):
                        try:
                            junk.unlink(missing_ok=True)
                        except OSError:
                            pass
                if not list(parent_artiste.iterdir()):
                    try:
                        parent_artiste.rmdir()
                    except OSError:
                        pass

    if corbeille and journal:
        journal_path.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    return nb


def supprimer_album(
    album_path: Path,
    racine: str | Path,
    *,
    corbeille: bool = True,
) -> None:
    """Supprime ou déplace en corbeille l'intégralité d'un album et nettoie l'artiste parent si vide."""
    base = Path(racine)
    parent_artiste = album_path.parent
    supprimer_fichiers([album_path], racine, corbeille=corbeille)
    if parent_artiste.exists() and parent_artiste != base:
        for junk in parent_artiste.iterdir():
            if junk.is_file() and junk.name.lower() in ("thumbs.db", ".ds_store", "desktop.ini"):
                try:
                    junk.unlink(missing_ok=True)
                except OSError:
                    pass
        if not list(parent_artiste.iterdir()):
            try:
                parent_artiste.rmdir()
            except OSError:
                pass


def annuler(racine: str | Path) -> int:
    """Restaure les fichiers et dossiers depuis le journal d'annulation."""
    base = Path(racine)
    journal_path = chemin_journal_doublons(base)
    if not journal_path.is_file():
        raise FileNotFoundError(f"Aucun journal d'annulation trouvé pour {racine}")

    entrees = json.loads(journal_path.read_text(encoding="utf-8"))
    n = 0
    for e in reversed(entrees):
        de, vers = Path(e["de"]), Path(e["vers"])
        if de.exists() and not vers.exists():
            vers.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(de), str(vers))
            n += 1

    journal_path.unlink(missing_ok=True)
    return n
