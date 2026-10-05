"""Transférer et fusionner plusieurs dossiers sources vers une bibliothèque musicale unique via Robocopy.

Arborescence stricte attendue pour chaque dossier source :
    <Dossier Source> / <Artiste> / <Album> / <fichiers audio>
    (avec éventuellement <Dossier Source> / <Artiste> / Singles / ...)

Processus :
1. Validation stricte de l'arborescence Artiste / Album de chaque dossier source sélectionné.
2. Prévisualisation des transferts et détection des collisions éventuelles.
3. Transfert vers le dossier de destination unique via robocopy (préservation métadonnées et horodatages).
4. Suppression du dossier source après confirmation de la réussite du transfert.
5. Génération en mémoire d'un journal de transfert (JSON et texte) téléchargeable sans écriture parasite sur le disque.
"""

from __future__ import annotations

import datetime
import json
import os
import shutil
import subprocess
from collections.abc import Callable
from dataclasses import dataclass, field
from pathlib import Path

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

FICHIERS_JUNK = {"thumbs.db", ".ds_store", "desktop.ini"}


@dataclass
class FichierTransfert:
    source: Path
    destination: Path
    taille: int
    existe_deja: bool = False


@dataclass
class DossierSourceStatut:
    chemin: Path
    est_valide: bool
    nb_artistes: int = 0
    nb_albums: int = 0
    nb_fichiers: int = 0
    taille_totale: int = 0
    anomalies: list[str] = field(default_factory=list)


@dataclass
class PlanTransfert:
    sources: list[DossierSourceStatut]
    destination: Path
    tous_fichiers: list[FichierTransfert] = field(default_factory=list)
    collisions: list[FichierTransfert] = field(default_factory=list)
    peut_executer: bool = False


@dataclass
class ResultatTransfert:
    succes: bool
    sources_traitees: list[Path]
    nb_fichiers_copies: int
    journal_json: str
    journal_texte: str
    erreurs: list[str] = field(default_factory=list)


def valider_structure_source(dossier: str | Path) -> DossierSourceStatut:
    """Valide qu'un dossier source respecte strictement l'arborescence premier niveau Artiste, deuxième niveau Albums.

    :param dossier: Chemin du dossier source à contrôler.
    :return: Bilan de validation détaillé avec comptages et anomalies.
    """
    chemin = Path(dossier)
    if not chemin.exists():
        return DossierSourceStatut(
            chemin=chemin, est_valide=False, anomalies=["Le dossier source n'existe pas."]
        )
    if not chemin.is_dir():
        return DossierSourceStatut(
            chemin=chemin, est_valide=False, anomalies=["Le chemin spécifié n'est pas un dossier."]
        )

    anomalies: list[str] = []
    fichiers_audio_racine: list[str] = []

    # 1. Vérifier qu'aucun fichier audio n'est présent directement à la racine
    try:
        with os.scandir(chemin) as it:
            for entry in it:
                if entry.name.startswith((".", "_")) or entry.name.lower() in FICHIERS_JUNK:
                    continue
                if entry.is_file():
                    ext = os.path.splitext(entry.name)[1].lower()
                    if ext in EXT_AUDIO:
                        fichiers_audio_racine.append(entry.name)
    except OSError as e:
        return DossierSourceStatut(
            chemin=chemin, est_valide=False, anomalies=[f"Erreur d'accès au dossier : {e}"]
        )

    if fichiers_audio_racine:
        anomalies.append(
            f"Fichiers audio trouvés directement à la racine (au lieu d'être dans un dossier d'artiste) : "
            f"{', '.join(fichiers_audio_racine[:5])}"
            + (f" et {len(fichiers_audio_racine)-5} autre(s)..." if len(fichiers_audio_racine) > 5 else "")
        )

    # 2. Explorer les sous-dossiers (doivent être les artistes)
    artistes: list[Path] = []
    with os.scandir(chemin) as it:
        for entry in it:
            if entry.name.startswith((".", "_")):
                continue
            if entry.is_dir():
                artistes.append(Path(entry.path))

    if not artistes:
        anomalies.append("Aucun sous-dossier d'artiste trouvé à la racine.")

    nb_albums = 0
    nb_fichiers = 0
    taille_totale = 0

    for artiste in artistes:
        # Vérifier si des fichiers audio sont directement sous l'artiste (hors d'un album)
        pistes_sous_artiste: list[str] = []
        albums_artiste: list[Path] = []

        try:
            with os.scandir(artiste) as it:
                for entry in it:
                    if entry.name.startswith((".", "_")) or entry.name.lower() in FICHIERS_JUNK:
                        continue
                    if entry.is_file():
                        ext = os.path.splitext(entry.name)[1].lower()
                        if ext in EXT_AUDIO:
                            pistes_sous_artiste.append(entry.name)
                    elif entry.is_dir():
                        albums_artiste.append(Path(entry.path))
        except OSError as e:
            anomalies.append(f"Impossible de scanner l'artiste '{artiste.name}' : {e}")
            continue

        if pistes_sous_artiste:
            anomalies.append(
                f"Pistes audio orphelines sous l'artiste '{artiste.name}' hors d'un album : "
                f"{', '.join(pistes_sous_artiste[:3])}"
            )

        if not albums_artiste:
            anomalies.append(f"L'artiste '{artiste.name}' ne contient aucun dossier d'album.")

        nb_albums += len(albums_artiste)

        # Calculer le nombre de fichiers et la taille totale
        for alb in albums_artiste:
            for root, _dirs, files in os.walk(alb):
                for f in files:
                    if f.lower() in FICHIERS_JUNK:
                        continue
                    p = Path(root) / f
                    nb_fichiers += 1
                    try:
                        taille_totale += p.stat().st_size
                    except OSError:
                        pass

    est_valide = len(anomalies) == 0 and len(artistes) > 0

    return DossierSourceStatut(
        chemin=chemin,
        est_valide=est_valide,
        nb_artistes=len(artistes),
        nb_albums=nb_albums,
        nb_fichiers=nb_fichiers,
        taille_totale=taille_totale,
        anomalies=anomalies,
    )


def preparer_transfert(
    sources: list[str | Path],
    destination: str | Path,
) -> PlanTransfert:
    """Analyse les dossiers sources et prépare le plan de transfert vers la destination.

    :param sources: Liste des chemins des dossiers sources.
    :param destination: Chemin de la bibliothèque cible.
    :return: Plan de transfert avec vérification de validité et détection des collisions.
    """
    dest = Path(destination)
    statuts_sources: list[DossierSourceStatut] = []
    tous_fichiers: list[FichierTransfert] = []
    collisions: list[FichierTransfert] = []

    for src in sources:
        st_src = valider_structure_source(src)
        statuts_sources.append(st_src)

        if st_src.est_valide:
            for root, _dirs, files in os.walk(st_src.chemin):
                for f in files:
                    if f.lower() in FICHIERS_JUNK or f.startswith((".", "_")):
                        continue
                    p_src = Path(root) / f
                    rel = p_src.relative_to(st_src.chemin)
                    p_dst = dest / rel
                    try:
                        taille = p_src.stat().st_size
                    except OSError:
                        taille = 0

                    existe = p_dst.exists()
                    item = FichierTransfert(
                        source=p_src,
                        destination=p_dst,
                        taille=taille,
                        existe_deja=existe,
                    )
                    tous_fichiers.append(item)
                    if existe:
                        collisions.append(item)

    peut_executer = (
        len(statuts_sources) > 0
        and all(s.est_valide for s in statuts_sources)
        and dest.is_dir()
    )

    return PlanTransfert(
        sources=statuts_sources,
        destination=dest,
        tous_fichiers=tous_fichiers,
        collisions=collisions,
        peut_executer=peut_executer,
    )


def executer_transfert_robocopy(
    plan: PlanTransfert,
    *,
    log: Callable[[str], None] | None = None,
) -> ResultatTransfert:
    """Exécute le transfert des dossiers sources vers la destination via Robocopy et supprime les sources à la fin.

    Génère un journal complet de restauration en mémoire sans écrire de fichier sur le disque.

    :param plan: Plan de transfert validé.
    :param log: Callback de progression.
    :return: Résultat du transfert avec journaux téléchargeables.
    """

    def _log(m: str) -> None:
        if log:
            log(m)

    if not plan.peut_executer:
        return ResultatTransfert(
            succes=False,
            sources_traitees=[],
            nb_fichiers_copies=0,
            journal_json="",
            journal_texte="",
            erreurs=["Le plan de transfert n'est pas exécutable (dossiers invalides ou destination absente)."],
        )

    date_iso = datetime.datetime.now().isoformat()
    erreurs: list[str] = []
    sources_traitees: list[Path] = []
    nb_copies = 0

    a_robocopy = shutil.which("robocopy") is not None

    for source_statut in plan.sources:
        src = source_statut.chemin
        _log(f"📦 Début du transfert de : {src} vers {plan.destination}")

        if a_robocopy:
            # Commande robocopy : copie récursive avec horodatages, silencieuse, sans retries infinis
            cmd = [
                "robocopy",
                str(src),
                str(plan.destination),
                "/E",
                "/COPY:DAT",
                "/DCOPY:DAT",
                "/R:2",
                "/W:1",
                "/NP",
                "/NFL",
                "/NDL",
            ]
            try:
                proc = subprocess.run(cmd, capture_output=True, text=True, errors="replace")
                # Codes de retour Robocopy : < 8 signifie succès
                if proc.returncode >= 8:
                    erreurs.append(
                        f"Échec Robocopy pour '{src}' (code {proc.returncode}) : {proc.stderr or proc.stdout}"
                    )
                    continue
            except OSError as e:
                erreurs.append(f"Impossible de lancer Robocopy pour '{src}' : {e}")
                continue
        else:
            # Fallback en environnement sans robocopy
            try:
                for f_item in plan.tous_fichiers:
                    if src in f_item.source.parents:
                        f_item.destination.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copy2(f_item.source, f_item.destination)
            except OSError as e:
                erreurs.append(f"Erreur de copie pour '{src}' : {e}")
                continue

        # Vérification et suppression du dossier source après copie réussie
        try:
            shutil.rmtree(src)
            sources_traitees.append(src)
            _log(f"🧹 Dossier source supprimé avec succès : {src}")
        except OSError as e:
            erreurs.append(f"Copie effectuée mais impossible de supprimer le dossier source '{src}' : {e}")

    fichiers_traites = [
        f for f in plan.tous_fichiers if any(s in f.source.parents for s in sources_traitees)
    ]
    nb_copies = len(fichiers_traites)

    # Construction du journal structuré JSON pour restauration éventuelle
    donnees_journal = {
        "date_transfert": date_iso,
        "destination": str(plan.destination),
        "sources_transferees": [str(s) for s in sources_traitees],
        "nb_fichiers_transferes": nb_copies,
        "fichiers": [
            {
                "source_origine": str(item.source),
                "destination_actuelle": str(item.destination),
                "taille": item.taille,
            }
            for item in fichiers_traites
        ],
    }
    journal_json = json.dumps(donnees_journal, ensure_ascii=False, indent=2)

    # Construction du journal texte lisible
    lignes_texte = [
        "============================================================",
        "JOURNAL DE TRANSFERT ROBOCOPY VERS LA BIBLIOTHÈQUE",
        "============================================================",
        f"Date : {date_iso}",
        f"Destination finale : {plan.destination}",
        f"Dossiers sources transférés ({len(sources_traitees)}) :",
    ]
    for s in sources_traitees:
        lignes_texte.append(f"  • {s}")
    lignes_texte.append(f"\nNombre total de fichiers transférés : {nb_copies}")
    lignes_texte.append("\n--- DÉTAIL DES FICHIERS ---")
    for item in fichiers_traites:
        lignes_texte.append(f"{item.source}  →  {item.destination}")

    if erreurs:
        lignes_texte.append("\n--- ERREURS RENCONTRÉES ---")
        for err in erreurs:
            lignes_texte.append(f"⚠️ {err}")

    lignes_texte.append("\nFin du transfert.")
    journal_texte = "\n".join(lignes_texte)

    succes = len(erreurs) == 0 and len(sources_traitees) == len(plan.sources)

    return ResultatTransfert(
        succes=succes,
        sources_traitees=sources_traitees,
        nb_fichiers_copies=nb_copies,
        journal_json=journal_json,
        journal_texte=journal_texte,
        erreurs=erreurs,
    )
