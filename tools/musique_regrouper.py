"""Regrouper les albums d'une bibliothèque musicale scindés entre plusieurs artistes.

Typiquement pour des albums acquis sur Bandcamp ou des compilations où chaque piste
ou groupe de pistes a été classé sous son artiste individuel au lieu d'être unifié
sous un seul artiste ou sous "Various Artists".

Arborescence attendue :
    <racine> / <Artiste> / <Album> / <fichiers audio>
    (avec éventuellement <racine> / <Artiste> / Singles / ignoré)

Règles de regroupement :
1. Un album est considéré « segmenté » s'il possède le même nom (normalisé) dans
   les répertoires d'au moins deux artistes différents.
2. L'album est regroupé chez l'artiste qui possède le plus grand nombre de titres
   de cet album.
3. Si aucun artiste ne détient au moins le seuil minimum de titres (par défaut 20 %),
   l'album est regroupé dans un dossier de repli (par défaut "Various Artists").
4. Tous les fichiers de l'album (pistes audio, pochettes, métadonnées) sont transférés
   vers le dossier d'album cible.
5. Les dossiers d'albums sources vidés sont envoyés en corbeille
   ('_albums_vides_a_supprimer/') ou supprimés, avec nettoyage des dossiers artistes
   devenus vides.
6. Un journal d'annulation (.regrouper_undo.json) permet de restaurer la structure initiale.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import unicodedata
from collections import defaultdict
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
NOM_CORBEILLE_REGROUPER = "_albums_vides_a_supprimer"
NOM_VARIOUS_ARTISTS_DEFAUT = "Various Artists"
SEUIL_MAJORITAIRE_DEFAUT = 0.20
FICHIERS_JUNK = {"thumbs.db", ".ds_store", "desktop.ini"}

Progression = Callable[[int, int], None]


def chemin_journal_regroupement(racine: str | Path) -> Path:
    """Renvoie le chemin du journal d'annulation stocké côté application."""
    return get_chemin_journal(racine, "regrouper")


def normaliser_nom_album(nom: str) -> str:
    """Normalise le nom d'un album pour la détection de regroupement.

    Insensible à la casse, aux accents diacritiques, aux espaces multiples et à la ponctuation simple.
    """
    texte = nom.strip()
    # Décomposition NFKD pour retirer les accents
    nfkd = unicodedata.normalize("NFKD", texte)
    sans_accents = "".join(c for c in nfkd if not unicodedata.combining(c))
    # Minuscules et normalisation des espaces
    nettoye = re.sub(r"\s+", " ", sans_accents).casefold().strip()
    # Unifier les tirets
    nettoye = re.sub(r"[-–—]", "-", nettoye)
    return nettoye


def _sous_dossiers_visibles(chemin: Path) -> list[Path]:
    """Liste les sous-dossiers directs visibles (hors '.' et '_')."""
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
    """Liste récursivement les fichiers audio d'un album."""
    fichiers: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(album_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for nom in filenames:
            ext = os.path.splitext(nom)[1].lower()
            if ext in EXT_AUDIO:
                fichiers.append(Path(dirpath) / nom)
    return sorted(fichiers)


def _tous_les_fichiers_album(album_dir: Path) -> list[Path]:
    """Liste tous les fichiers d'un dossier album (audio, images, livrets...), hors junk."""
    fichiers: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(album_dir):
        dirnames[:] = [d for d in dirnames if not d.startswith((".", "_"))]
        for nom in filenames:
            if nom.lower() in FICHIERS_JUNK:
                continue
            fichiers.append(Path(dirpath) / nom)
    return sorted(fichiers)


def _hash_fichier(path: Path, taille_bloc: int = 1 << 20) -> str:
    """Calcule l'empreinte SHA-1 d'un fichier."""
    h = hashlib.sha1()
    with open(path, "rb") as f:
        while bloc := f.read(taille_bloc):
            h.update(bloc)
    return h.hexdigest()


def _nom_libre(dossier: Path, nom: str, reserves: set[str]) -> Path:
    """Trouve un chemin disponible dans `dossier` sans collision physique ni logique."""
    cible = dossier / nom
    cle = str(cible).lower()
    if cle not in reserves and not cible.exists():
        reserves.add(cle)
        return cible
    tige, ext = os.path.splitext(nom)
    i = 2
    while True:
        cible = dossier / f"{tige} ({i}){ext}"
        cle_i = str(cible).lower()
        if cle_i not in reserves and not cible.exists():
            reserves.add(cle_i)
            return cible
        i += 1


@dataclass
class OccurrenceAlbum:
    artiste: str
    dossier_album: Path
    pistes_audio: list[Path]
    tous_fichiers: list[Path]


@dataclass
class ActionFichier:
    source: Path
    destination: Path
    est_identique_deja_present: bool = False


@dataclass
class AlbumSegment:
    cle_normalisee: str
    nom_album_affiche: str
    occurrences: list[OccurrenceAlbum]
    total_pistes: int
    artiste_cible: str
    dossier_album_cible: Path
    raison_cible: str
    ratio_max: float
    est_repli_various: bool
    repartition: dict[str, int] = field(default_factory=dict)


@dataclass
class PlanRegroupement:
    racine: Path
    albums: list[AlbumSegment]
    actions_fichiers: list[ActionFichier]
    dossiers_sources_a_nettoyer: list[Path]


@dataclass
class ResultatRegroupement:
    nb_albums: int
    nb_fichiers_deplaces: int
    nb_doublons_ignores: int
    nb_dossiers_nettoyes: int
    journal: Path | None
    rapport_texte: str = ""
    erreurs: list[str] = field(default_factory=list)


def analyser_regroupement(
    racine: str | Path,
    *,
    seuil_pct: float = SEUIL_MAJORITAIRE_DEFAUT,
    dossier_repli: str = NOM_VARIOUS_ARTISTS_DEFAUT,
    progress: Progression | None = None,
) -> PlanRegroupement:
    """Analyse la bibliothèque pour identifier les albums segmentés et calculer leur plan de regroupement.

    :param racine: Dossier racine de la bibliothèque (ex: M:/musiques/__autres).
    :param seuil_pct: Seuil minimum de pistes (entre 0.0 et 1.0) qu'un artiste doit détenir
                      pour être choisi comme cible. Si aucun artiste n'atteint ce seuil,
                      le regroupement s'effectue dans `dossier_repli`.
    :param dossier_repli: Nom du dossier d'artiste de repli (ex: "Various Artists").
    :param progress: Callback de suivi (faits, total).
    :return: Plan de regroupement détaillé.
    """
    base = Path(racine)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    artistes = _sous_dossiers_visibles(base)
    total_artistes = len(artistes)

    albums_par_cle: dict[str, list[OccurrenceAlbum]] = defaultdict(list)

    for i, artiste in enumerate(artistes, 1):
        for dossier_album in _sous_dossiers_visibles(artiste):
            if dossier_album.name.lower() == NOM_DOSSIER_SINGLES.lower():
                continue

            pistes = _fichiers_audio_album(dossier_album)
            if not pistes:
                continue

            tous = _tous_les_fichiers_album(dossier_album)
            cle = normaliser_nom_album(dossier_album.name)
            if cle:
                albums_par_cle[cle].append(
                    OccurrenceAlbum(
                        artiste=artiste.name,
                        dossier_album=dossier_album,
                        pistes_audio=pistes,
                        tous_fichiers=tous,
                    )
                )

        if progress:
            progress(i, total_artistes)

    # Filtrer les albums segmentés (présents dans >= 2 dossiers d'artistes distincts)
    albums_segmentes: list[AlbumSegment] = []
    actions_fichiers: list[ActionFichier] = []
    dossiers_sources_a_nettoyer: list[Path] = []
    reserves_fichiers: set[str] = set()

    for cle, occs in albums_par_cle.items():
        # Vérifier si l'album est scindé entre plusieurs dossiers artistes différents
        artistes_distincts = {occ.artiste for occ in occs}
        if len(artistes_distincts) < 2:
            continue

        total_pistes = sum(len(occ.pistes_audio) for occ in occs)
        if total_pistes == 0:
            continue

        repartition: dict[str, int] = defaultdict(int)
        for occ in occs:
            repartition[occ.artiste] += len(occ.pistes_audio)

        # Identifier l'artiste ayant le plus grand nombre de titres
        # En cas d'égalité sur le nombre de pistes, départage alphabétique croissant A-Z
        artiste_max = min(
            repartition.keys(),
            key=lambda a: (-repartition[a], a.lower()),
        )
        max_pistes = repartition[artiste_max]
        ratio_max = max_pistes / total_pistes

        # Règle de décision de l'artiste cible
        if ratio_max >= seuil_pct:
            artiste_cible = artiste_max
            # Utiliser le nom réel du dossier de l'album chez cet artiste
            occ_cible = next(occ for occ in occs if occ.artiste == artiste_cible)
            nom_album_affiche = occ_cible.dossier_album.name
            dossier_album_cible = occ_cible.dossier_album
            raison_cible = (
                f"Artiste majoritaire ({max_pistes}/{total_pistes} pistes, {ratio_max:.0%})"
            )
            est_repli_various = False
        else:
            artiste_cible = dossier_repli
            # Utiliser le nom d'album de l'occurrence ayant le plus de pistes
            occ_principale = max(occs, key=lambda occ: len(occ.pistes_audio))
            nom_album_affiche = occ_principale.dossier_album.name
            dossier_album_cible = base / dossier_repli / nom_album_affiche
            raison_cible = (
                f"Aucun artiste >= {seuil_pct:.0%} (max : {artiste_max} à {ratio_max:.0%}) "
                f"→ repli vers {dossier_repli}"
            )
            est_repli_various = True

        album_seg = AlbumSegment(
            cle_normalisee=cle,
            nom_album_affiche=nom_album_affiche,
            occurrences=occs,
            total_pistes=total_pistes,
            artiste_cible=artiste_cible,
            dossier_album_cible=dossier_album_cible,
            raison_cible=raison_cible,
            ratio_max=ratio_max,
            est_repli_various=est_repli_various,
            repartition=dict(repartition),
        )
        albums_segmentes.append(album_seg)

        # Établir les transferts de fichiers pour cet album
        for occ in occs:
            if occ.dossier_album.resolve() == dossier_album_cible.resolve():
                continue  # Dossier déjà sur place, rien à transférer depuis lui-même

            dossiers_sources_a_nettoyer.append(occ.dossier_album)

            for f_src in occ.tous_fichiers:
                rel = f_src.relative_to(occ.dossier_album)
                dest_theorique = dossier_album_cible / rel

                if dest_theorique.exists():
                    try:
                        # Vérifier si c'est un clone binaire exact
                        if (
                            f_src.stat().st_size == dest_theorique.stat().st_size
                            and _hash_fichier(f_src) == _hash_fichier(dest_theorique)
                        ):
                            actions_fichiers.append(
                                ActionFichier(
                                    source=f_src,
                                    destination=dest_theorique,
                                    est_identique_deja_present=True,
                                )
                            )
                            continue
                    except OSError:
                        pass

                # Trouver un nom libre si collision ou réservation
                dest_finale = _nom_libre(
                    dest_theorique.parent, dest_theorique.name, reserves_fichiers
                )
                actions_fichiers.append(
                    ActionFichier(
                        source=f_src,
                        destination=dest_finale,
                        est_identique_deja_present=False,
                    )
                )

    return PlanRegroupement(
        racine=base,
        albums=albums_segmentes,
        actions_fichiers=actions_fichiers,
        dossiers_sources_a_nettoyer=dossiers_sources_a_nettoyer,
    )


def appliquer_regroupement(
    plan: PlanRegroupement,
    *,
    utiliser_corbeille: bool = True,
    supprimer_artistes_vides: bool = True,
    log: Callable[[str], None] | None = None,
) -> ResultatRegroupement:
    """Exécute les transferts de fichiers et le nettoyage des dossiers vidés avec journal d'annulation.

    :param plan: Le plan de regroupement précalculé.
    :param utiliser_corbeille: Si True, déplace les dossiers vidés dans
                              `<racine>/_albums_vides_a_supprimer/`. Si False, les supprime.
    :param supprimer_artistes_vides: Si True, supprime également le dossier de l'artiste
                                    s'il est totalement vidé après l'opération.
    :param log: Callback pour afficher les messages d'avancement.
    :return: Rapport du résultat d'exécution.
    """

    def _log(msg: str) -> None:
        if log:
            log(msg)

    journal: list[dict] = []
    erreurs: list[str] = []
    nb_deplaces = 0
    nb_doublons = 0
    nb_dossiers_nettoyes = 0

    corbeille = plan.racine / NOM_CORBEILLE_REGROUPER

    # 1. Déplacement des fichiers
    for action in plan.actions_fichiers:
        if action.est_identique_deja_present:
            nb_doublons += 1
            # Fichier identique déjà présent dans la cible : on peut simplement le supprimer
            # de la source pour permettre de vider le dossier source.
            try:
                action.source.unlink(missing_ok=True)
            except OSError as e:
                erreurs.append(f"Suppression doublon source {action.source} : {e}")
            continue

        try:
            action.destination.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(action.source), str(action.destination))
            journal.append(
                {
                    "type": "move",
                    "de": str(action.destination),
                    "vers": str(action.source),
                }
            )
            nb_deplaces += 1
            _log(f"→ Déplacé : {action.source.name} vers {action.destination.parent.name}/")
        except OSError as e:
            erreurs.append(f"Transfert {action.source} vers {action.destination} : {e}")

    # 2. Nettoyage des dossiers d'albums sources vidés
    artistes_touches: set[Path] = set()
    lignes_rapport: list[str] = [
        "============================================================",
        "RAPPORT D'EXÉCUTION — REGROUPEMENT D'ALBUMS MULTI-ARTISTES",
        "============================================================",
        f"Racine : {plan.racine}",
        f"Nombre d'albums segmentés traités : {len(plan.albums)}",
        f"Fichiers déplacés : {nb_deplaces}",
        f"Doublons identiques ignorés : {nb_doublons}",
        "",
        "--- DÉTAIL PAR ALBUM ---",
    ]

    for alb in plan.albums:
        repart_str = ", ".join(f"{art}: {nb}" for art, nb in alb.repartition.items())
        lignes_rapport.append(f"\n[Album] {alb.nom_album_affiche}")
        lignes_rapport.append(f"  • Répartition d'origine : {repart_str} (Total: {alb.total_pistes} pistes)")
        lignes_rapport.append(f"  • Destination : {alb.artiste_cible} / {alb.dossier_album_cible.name}")
        lignes_rapport.append(f"  • Règle : {alb.raison_cible}")
        lignes_rapport.append("  • Fichiers transférés :")

        acts = [
            a
            for a in plan.actions_fichiers
            if alb.dossier_album_cible.resolve() in a.destination.resolve().parents
            or a.destination.resolve() == alb.dossier_album_cible.resolve()
        ]
        for a in acts:
            rel_src = a.source.relative_to(plan.racine)
            rel_dst = a.destination.relative_to(plan.racine)
            if a.est_identique_deja_present:
                lignes_rapport.append(f"    - {rel_src} → (Doublon identique supprimé de la source)")
            else:
                lignes_rapport.append(f"    - {rel_src} → {rel_dst}")

    for dossier_album in plan.dossiers_sources_a_nettoyer:
        if not dossier_album.exists():
            continue

        parent_artiste = dossier_album.parent
        artistes_touches.add(parent_artiste)

        # Nettoyer les fichiers junk résiduels (.DS_Store, Thumbs.db)
        try:
            for root, _dirs, files in os.walk(dossier_album):
                for f in files:
                    if f.lower() in FICHIERS_JUNK:
                        try:
                            (Path(root) / f).unlink(missing_ok=True)
                        except OSError:
                            pass
        except OSError:
            pass

        # Nettoyer d'abord les sous-dossiers devenus vides (ordre bas en haut)
        try:
            for root, dirs, _files in os.walk(dossier_album, topdown=False):
                for d in dirs:
                    p = Path(root) / d
                    try:
                        if not list(p.iterdir()):
                            p.rmdir()
                    except OSError:
                        pass
        except OSError:
            pass

        # Vérifier si le dossier d'album est vide
        est_vide = False
        try:
            contenu_restant = list(dossier_album.iterdir())
            est_vide = len(contenu_restant) == 0
        except OSError as e:
            erreurs.append(f"Inspection dossier {dossier_album} : {e}")

        if est_vide:
            if utiliser_corbeille:
                try:
                    rel_artiste = parent_artiste.name
                    dest_corbeille = corbeille / rel_artiste / dossier_album.name
                    dest_corbeille.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(dossier_album), str(dest_corbeille))
                    journal.append(
                        {
                            "type": "corbeille_dossier",
                            "de": str(dest_corbeille),
                            "vers": str(dossier_album),
                        }
                    )
                    nb_dossiers_nettoyes += 1
                    _log(f"🗑️ Mis en corbeille : {rel_artiste}/{dossier_album.name}")
                except OSError as e:
                    erreurs.append(f"Mise en corbeille {dossier_album} : {e}")
            else:
                try:
                    dossier_album.rmdir()
                    nb_dossiers_nettoyes += 1
                    _log(f"🧹 Supprimé (vide) : {parent_artiste.name}/{dossier_album.name}")
                except OSError as e:
                    erreurs.append(f"Suppression dossier vide {dossier_album} : {e}")
        else:
            erreurs.append(
                f"Le dossier source {dossier_album} contient encore des fichiers non transférés et n'a pas été supprimé."
            )

    # 3. Nettoyage des dossiers artistes parents s'ils sont devenus totalement vides
    if supprimer_artistes_vides:
        for dossier_artiste in artistes_touches:
            if dossier_artiste.exists() and dossier_artiste.resolve() != plan.racine.resolve():
                try:
                    for f in dossier_artiste.iterdir():
                        if f.is_file() and f.name.lower() in FICHIERS_JUNK:
                            try:
                                f.unlink(missing_ok=True)
                            except OSError:
                                pass
                    if not list(dossier_artiste.iterdir()):
                        dossier_artiste.rmdir()
                        _log(f"🧹 Dossier artiste vidé supprimé : {dossier_artiste.name}")
                except OSError:
                    pass

    lignes_rapport.append("\n--- SYNTHÈSE NETTOYAGE ---")
    lignes_rapport.append(f"Dossiers sources nettoyés : {nb_dossiers_nettoyes}")
    if erreurs:
        lignes_rapport.append(f"\nErreurs rencontrées ({len(erreurs)}) :")
        for err in erreurs:
            lignes_rapport.append(f"  • {err}")
    lignes_rapport.append("\nOpération terminée.")
    rapport_complet = "\n".join(lignes_rapport)

    # 4. Écriture du journal d'annulation côté application
    chemin_journal = chemin_journal_regroupement(plan.racine)
    try:
        chemin_journal.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )
    except OSError as e:
        erreurs.append(f"Écriture journal d'annulation ({chemin_journal}) : {e}")

    return ResultatRegroupement(
        nb_albums=len(plan.albums),
        nb_fichiers_deplaces=nb_deplaces,
        nb_doublons_ignores=nb_doublons,
        nb_dossiers_nettoyes=nb_dossiers_nettoyes,
        journal=chemin_journal if journal else None,
        rapport_texte=rapport_complet,
        erreurs=erreurs,
    )


def annuler_regroupement(racine: str | Path) -> int:
    """Restaure les fichiers et dossiers déplacés d'après le journal.

    :param racine: Dossier racine de la bibliothèque.
    :return: Nombre d'actions annulées avec succès.
    """
    base = Path(racine)
    chemin = chemin_journal_regroupement(base)
    if not chemin.is_file():
        raise FileNotFoundError(f"Aucun journal de regroupement pour {base}")

    entrees = json.loads(chemin.read_text(encoding="utf-8"))
    nb_annules = 0

    for item in reversed(entrees):
        de = Path(item["de"])
        vers = Path(item["vers"])

        if item.get("type") in ("move", "corbeille_dossier"):
            if de.exists():
                try:
                    vers.parent.mkdir(parents=True, exist_ok=True)
                    shutil.move(str(de), str(vers))
                    nb_annules += 1
                except OSError:
                    pass

    # Supprimer les dossiers corbeille orphelins si vides
    corbeille = base / NOM_CORBEILLE_REGROUPER
    if corbeille.is_dir():
        try:
            for root, dirs, files in os.walk(corbeille, topdown=False):
                for d in dirs:
                    p = Path(root) / d
                    if p.is_dir() and not list(p.iterdir()):
                        p.rmdir()
            if not list(corbeille.iterdir()):
                corbeille.rmdir()
        except OSError:
            pass

    # Supprimer le journal une fois restauré
    try:
        chemin.unlink(missing_ok=True)
    except OSError:
        pass

    return nb_annules
