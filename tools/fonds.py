"""Appariement de fonds d'écran paysage ↔ portrait (SIFT + RANSAC).

Le portrait est un recadrage zoomé d'une portion du paysage (parfois avec du
contenu en haut/bas absent du paysage). On apparie par mise en correspondance
géométrique : SIFT (invariant à l'échelle) + ratio test + homographie RANSAC.
Le score d'un couple = nombre de points « inliers » géométriquement cohérents.

Stratégie : on apparie **du plus sûr au moins sûr**. À chaque tour on prend le
score maximum de toute la matrice, on verrouille ce couple et on retire les deux
images du pool — les paires certaines cessent ainsi de polluer les cas ambigus.

OpenCV est importé paresseusement (dépendance de base, ~60 Mo, sans torch).
"""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

EXT_IMAGES = (".png", ".jpg", ".jpeg", ".webp", ".bmp")

# Paramètres par défaut (calés sur la validation des couples étiquetés).
MAX_DIM = 900
NFEATURES = 1500
RATIO_LOWE = 0.75
RANSAC_REPROJ = 5.0
SEUIL_INLIERS = 30  # plancher : en dessous, on n'apparie pas
SEUIL_CERTAIN = 60  # au-dessus (ou forte marge) : couple « sûr »


def orientation(taille: tuple[int, int]) -> str:
    """'paysage' si large, 'portrait' si haut, 'carre' sinon."""
    w, h = taille
    return "paysage" if w > h else "portrait" if h > w else "carre"


def _lire_gris(chemin: Path):
    """Charge une image en niveaux de gris, réduite à MAX_DIM (gère les chemins Unicode)."""
    import cv2
    import numpy as np

    data = np.fromfile(str(chemin), dtype=np.uint8)
    im = cv2.imdecode(data, cv2.IMREAD_GRAYSCALE)
    if im is None:
        raise ValueError(f"Image illisible : {chemin}")
    h, w = im.shape
    s = MAX_DIM / max(h, w)
    if s < 1:
        im = cv2.resize(im, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA)
    return im


def _moteur_sift():
    import cv2

    return cv2.SIFT_create(nfeatures=NFEATURES)


def descripteurs(chemin: Path, sift=None):
    """(keypoints, descripteurs) SIFT d'une image."""
    sift = sift or _moteur_sift()
    return sift.detectAndCompute(_lire_gris(chemin), None)


def compter_inliers(desc_a, desc_b) -> int:
    """Nombre de correspondances géométriquement cohérentes entre deux images.

    Score élevé (dizaines à centaines) = l'une est un recadrage de l'autre.
    """
    import cv2
    import numpy as np

    kp1, des1 = desc_a
    kp2, des2 = desc_b
    if des1 is None or des2 is None or len(kp1) < 4 or len(kp2) < 4:
        return 0

    bf = cv2.BFMatcher(cv2.NORM_L2)
    matches = bf.knnMatch(des1, des2, k=2)
    bons = [m for m, n in matches if m.distance < RATIO_LOWE * n.distance]
    if len(bons) < 4:
        return 0

    src = np.float32([kp1[m.queryIdx].pt for m in bons]).reshape(-1, 1, 2)
    dst = np.float32([kp2[m.trainIdx].pt for m in bons]).reshape(-1, 1, 2)
    _, mask = cv2.findHomography(src, dst, cv2.RANSAC, RANSAC_REPROJ)
    return int(mask.sum()) if mask is not None else 0


@dataclass
class Couple:
    paysage: Path
    portrait: Path
    score: int  # inliers du couple retenu
    second: int  # meilleur score concurrent (marge de certitude)

    @property
    def certain(self) -> bool:
        """Sûr si beaucoup d'inliers, ou nette avance sur le concurrent."""
        return self.score >= SEUIL_CERTAIN or self.score >= 3 * max(self.second, 1)


@dataclass
class Resultat:
    couples: list[Couple]
    paysages_seuls: list[Path]
    portraits_seuls: list[Path]


def lister_images(dossier: Path) -> list[Path]:
    return sorted(
        f for f in dossier.iterdir() if f.is_file() and f.suffix.lower() in EXT_IMAGES
    )


def apparier(
    dossier_source: str | Path,
    *,
    seuil: int = SEUIL_INLIERS,
    log: Callable[[str], None] | None = None,
) -> Resultat:
    """Apparie paysages et portraits d'un dossier (du plus sûr au moins sûr).

    :param seuil: nombre minimum d'inliers pour valider un couple.
    """
    from PIL import Image

    base = Path(dossier_source)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    paysages: list[Path] = []
    portraits: list[Path] = []
    for f in lister_images(base):
        try:
            with Image.open(f) as im:
                ori = orientation(im.size)
        except Exception:
            continue
        if ori == "paysage":
            paysages.append(f)
        elif ori == "portrait":
            portraits.append(f)

    def _log(m: str) -> None:
        if log:
            log(m)

    _log(f"{len(paysages)} paysages, {len(portraits)} portraits.")
    if not paysages or not portraits:
        return Resultat([], paysages, portraits)

    sift = _moteur_sift()
    _log("Calcul des descripteurs SIFT…")
    d_pa = [descripteurs(p, sift) for p in paysages]
    d_po = [descripteurs(p, sift) for p in portraits]

    _log("Mise en correspondance…")
    # Matrice portraits × paysages.
    matrice: list[list[int]] = []
    for i, dpo in enumerate(d_po):
        ligne = [compter_inliers(dpo, dpa) for dpa in d_pa]
        matrice.append(ligne)
        _log(f"  portrait {i + 1}/{len(portraits)}")

    # Greedy : on retire chaque couple verrouillé du pool.
    libres_po = set(range(len(portraits)))
    libres_pa = set(range(len(paysages)))
    couples: list[Couple] = []
    while libres_po and libres_pa:
        meilleur = None  # (score, i, j)
        for i in libres_po:
            for j in libres_pa:
                s = matrice[i][j]
                if meilleur is None or s > meilleur[0]:
                    meilleur = (s, i, j)
        score, i, j = meilleur
        if score < seuil:
            break
        second = max(
            [matrice[i][jj] for jj in libres_pa if jj != j]
            + [matrice[ii][j] for ii in libres_po if ii != i]
            + [0]
        )
        couples.append(
            Couple(
                paysage=paysages[j], portrait=portraits[i], score=score, second=second
            )
        )
        libres_po.discard(i)
        libres_pa.discard(j)

    return Resultat(
        couples=couples,
        paysages_seuls=[paysages[j] for j in sorted(libres_pa)],
        portraits_seuls=[portraits[i] for i in sorted(libres_po)],
    )


# --- Déduplication et signatures --------------------------------------------

FICHIER_SIGNATURES = ".signatures_fonds.json"
FICHIER_UNDO = ".organisation_undo.json"


def _sha256(chemin: Path) -> str:
    """Calcul du SHA-256 par blocs de 64 Ko."""
    import hashlib

    h = hashlib.sha256()
    with open(chemin, "rb") as f:
        while chunk := f.read(65536):
            h.update(chunk)
    return h.hexdigest()


def _phash(chemin: Path):
    """Calcul de l'empreinte perceptuelle pHash."""
    import imagehash
    from PIL import Image

    with Image.open(chemin) as im:
        return imagehash.phash(im)


def lister_png_racine(
    dossier: str | Path,
    extensions: tuple[str, ...] = (".png", ".jpg", ".jpeg", ".webp"),
) -> list[Path]:
    """Liste uniquement les images situées directement à la racine du dossier (sans sous-dossiers)."""
    base = Path(dossier)
    if not base.is_dir():
        return []
    return sorted(
        f for f in base.iterdir() if f.is_file() and f.suffix.lower() in extensions
    )


def charger_signatures_destination(
    dossier_tries: str | Path,
    *,
    inclure_doublons: bool = True,
    log: Callable[[str], None] | None = None,
) -> tuple[dict[str, tuple[str, object]], Path]:
    """Charge ou calcule les signatures (SHA-256 et pHash) des fichiers déjà triés.

    Retourne (signatures, chemin_cache) où signatures est un dictionnaire :
    rel_path -> (sha256, phash_obj)
    """
    import imagehash

    base = Path(dossier_tries)
    base.mkdir(parents=True, exist_ok=True)
    cache_path = base / FICHIER_SIGNATURES

    cache: dict[str, dict] = {}
    if cache_path.is_file():
        try:
            cache = json.loads(cache_path.read_text(encoding="utf-8"))
        except Exception:
            cache = {}

    fichiers_cibles: list[Path] = []
    for pattern in ("*_pa.*", "*_po.*"):
        fichiers_cibles.extend(base.glob(pattern))

    dossier_doublons = base / "Doublons"
    if inclure_doublons and dossier_doublons.is_dir():
        fichiers_cibles.extend(f for f in dossier_doublons.iterdir() if f.is_file())

    fichiers_cibles = sorted(set(fichiers_cibles))
    if log and fichiers_cibles:
        log(f"Indexation de {len(fichiers_cibles)} fichier(s) dans la destination…")

    signatures: dict[str, tuple[str, object]] = {}
    mis_a_jour = False

    for f in fichiers_cibles:
        rel = str(f.relative_to(base)).replace("\\", "/")
        try:
            stat = f.stat()
            mtime = stat.st_mtime
            size = stat.st_size
        except OSError:
            continue

        cached = cache.get(rel)
        if (
            cached
            and cached.get("mtime") == mtime
            and cached.get("size") == size
            and "sha256" in cached
            and "phash" in cached
        ):
            sha = cached["sha256"]
            ph = imagehash.hex_to_hash(cached["phash"])
        else:
            try:
                sha = _sha256(f)
                ph_obj = _phash(f)
                ph = ph_obj
                cache[rel] = {
                    "sha256": sha,
                    "phash": str(ph_obj),
                    "mtime": mtime,
                    "size": size,
                }
                mis_a_jour = True
            except Exception:
                continue
        signatures[rel] = (sha, ph)

    if mis_a_jour:
        cache_path.write_text(
            json.dumps(cache, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    return signatures, cache_path


def empreintes_paysages(dossier_tries: str | Path) -> list[tuple[str, object]]:
    """Empreintes perceptuelles des paysages déjà triés (``NNN_pa.*``)."""
    base = Path(dossier_tries)
    if not base.is_dir():
        return []
    sortie = []
    for f in sorted(base.glob("*_pa.*")):
        try:
            sortie.append((f.stem, _phash(f)))
        except Exception:
            continue
    return sortie


def couple_deja_trie(
    paysage: str | Path, empreintes: list[tuple[str, object]], *, seuil_hash: int = 6
) -> str | None:
    """Retourne l'identifiant trié correspondant si le paysage y est déjà, sinon None."""
    if not empreintes:
        return None
    h = _phash(Path(paysage))
    for nom, he in empreintes:
        if (h - he) <= seuil_hash:
            return nom
    return None


# --- Rangement et organisation complète -------------------------------------


def prochain_id(dossier_tries: str | Path) -> int:
    """Prochain identifiant libre (max des ``NNN_pa`` existants + 1)."""
    base = Path(dossier_tries)
    ids = []
    for f in base.glob("*_pa.*"):
        prefix = f.stem.split("_")[0]
        if prefix.isdigit():
            ids.append(int(prefix))
    return (max(ids) + 1) if ids else 1


@dataclass
class PlanOrganisation:
    couples: list[Couple]
    doublons: list[tuple[Path, str]]  # (fichier_source, motif_doublon)
    orphelins: list[Path]  # images sans correspondance
    paysages_candidats: list[Path]
    portraits_candidats: list[Path]
    nb_source_total: int


def preparer_organisation(
    dossier_source: str | Path,
    dossier_tries: str | Path,
    *,
    seuil_inliers: int = SEUIL_INLIERS,
    seuil_phash: int = 4,
    log: Callable[[str], None] | None = None,
) -> PlanOrganisation:
    """Analyse un dossier source PNG (racine seule) et prépare le plan de rangement.

    1. Détecte les doublons contre le dossier trié et internes à la source.
    2. Sépare les images saines en paysages et portraits.
    3. Apparie par géométrie SIFT/RANSAC.
    4. Les images sans partenaire deviennent orphelines.
    """
    from PIL import Image

    src_base = Path(dossier_source)
    dst_base = Path(dossier_tries)
    if not src_base.is_dir():
        raise NotADirectoryError(f"Dossier source introuvable : {src_base}")
    if src_base.resolve() == dst_base.resolve():
        raise ValueError(
            "Le dossier source et le dossier de sortie doivent être distincts."
        )

    def _log(m: str) -> None:
        if log:
            log(m)

    fichiers_source = lister_png_racine(src_base)
    _log(f"{len(fichiers_source)} fichier(s) PNG trouvé(s) dans le dossier source.")
    if not fichiers_source:
        return PlanOrganisation(
            couples=[],
            doublons=[],
            orphelins=[],
            paysages_candidats=[],
            portraits_candidats=[],
            nb_source_total=0,
        )

    sigs_dst, _ = charger_signatures_destination(
        dst_base, inclure_doublons=True, log=_log
    )
    dst_sha_map = {sha: rel for rel, (sha, _) in sigs_dst.items()}
    dst_phash_list = [(rel, ph) for rel, (_, ph) in sigs_dst.items()]

    doublons: list[tuple[Path, str]] = []
    candidats: list[tuple[Path, str]] = []  # (fichier, orientation)
    orphelins: list[Path] = []

    src_sha_map: dict[str, str] = {}
    src_phash_list: list[tuple[str, object]] = []

    _log("Analyse des empreintes et détection des doublons…")
    for idx, f in enumerate(fichiers_source):
        try:
            with Image.open(f) as im:
                ori = orientation(im.size)
            sha = _sha256(f)
            ph = _phash(f)
        except Exception as err:
            _log(f"Fichier illisible {f.name} : {err}")
            orphelins.append(f)
            continue

        # 1.1 Doublon exact destination
        if sha in dst_sha_map:
            doublons.append((f, f"Copie exacte de {dst_sha_map[sha]}"))
            continue

        # 1.2 Doublon exact source
        if sha in src_sha_map:
            doublons.append((f, f"Copie exacte de {src_sha_map[sha]}"))
            continue

        # 1.3 Doublon perceptuel destination
        est_dup_dst = False
        for rel, dph in dst_phash_list:
            if (ph - dph) <= seuil_phash:
                doublons.append((f, f"Doublon visuel de {rel}"))
                est_dup_dst = True
                break
        if est_dup_dst:
            continue

        # 1.4 Doublon perceptuel source
        est_dup_src = False
        for sname, sph in src_phash_list:
            if (ph - sph) <= seuil_phash:
                doublons.append((f, f"Doublon visuel de {sname}"))
                est_dup_src = True
                break
        if est_dup_src:
            continue

        src_sha_map[sha] = f.name
        src_phash_list.append((f.name, ph))

        if ori in ("paysage", "portrait"):
            candidats.append((f, ori))
        else:
            orphelins.append(f)

    paysages = [f for f, ori in candidats if ori == "paysage"]
    portraits = [f for f, ori in candidats if ori == "portrait"]
    _log(
        f"{len(doublons)} doublon(s), {len(paysages)} paysage(s), {len(portraits)} portrait(s)."
    )

    if not paysages or not portraits:
        orphelins.extend(paysages)
        orphelins.extend(portraits)
        return PlanOrganisation(
            couples=[],
            doublons=doublons,
            orphelins=sorted(orphelins),
            paysages_candidats=paysages,
            portraits_candidats=portraits,
            nb_source_total=len(fichiers_source),
        )

    sift = _moteur_sift()
    _log("Calcul des descripteurs SIFT…")
    d_pa = [descripteurs(p, sift) for p in paysages]
    d_po = [descripteurs(p, sift) for p in portraits]

    _log("Mise en correspondance des couples…")
    matrice: list[list[int]] = []
    for i, dpo in enumerate(d_po):
        ligne = [compter_inliers(dpo, dpa) for dpa in d_pa]
        matrice.append(ligne)

    libres_po = set(range(len(portraits)))
    libres_pa = set(range(len(paysages)))
    couples: list[Couple] = []

    while libres_po and libres_pa:
        meilleur = None
        for i in libres_po:
            for j in libres_pa:
                s = matrice[i][j]
                if meilleur is None or s > meilleur[0]:
                    meilleur = (s, i, j)
        score, i, j = meilleur
        if score < seuil_inliers:
            break
        second = max(
            [matrice[i][jj] for jj in libres_pa if jj != j]
            + [matrice[ii][j] for ii in libres_po if ii != i]
            + [0]
        )
        couples.append(
            Couple(
                paysage=paysages[j], portrait=portraits[i], score=score, second=second
            )
        )
        libres_po.discard(i)
        libres_pa.discard(j)

    for j in libres_pa:
        orphelins.append(paysages[j])
    for i in libres_po:
        orphelins.append(portraits[i])

    return PlanOrganisation(
        couples=couples,
        doublons=doublons,
        orphelins=sorted(orphelins),
        paysages_candidats=paysages,
        portraits_candidats=portraits,
        nb_source_total=len(fichiers_source),
    )


def _cible_sans_ecraser(dossier: Path, nom_fichier: str) -> Path:
    """Garantit un chemin unique dans dossier en ajoutant un suffixe numérique si nécessaire."""
    dest = dossier / nom_fichier
    if not dest.exists():
        return dest
    stem = Path(nom_fichier).stem
    ext = Path(nom_fichier).suffix
    k = 1
    while (dossier / f"{stem}_{k}{ext}").exists():
        k += 1
    return dossier / f"{stem}_{k}{ext}"


def _transferer_image_png(src: Path, dst: Path, deplacer: bool = True) -> None:
    """Déplace ou copie une image vers sa destination en garantissant le format PNG."""
    from PIL import Image

    if src.suffix.lower() == ".png":
        if deplacer:
            shutil.move(str(src), str(dst))
        else:
            shutil.copy2(str(src), str(dst))
    else:
        with Image.open(src) as im:
            im.save(dst, "PNG")
        if deplacer:
            src.unlink()


def appliquer_organisation(
    plan: PlanOrganisation,
    dossier_tries: str | Path,
    *,
    deplacer: bool = True,
    supprimer_doublons: bool = False,
    couples_selectionnes: list[Couple] | None = None,
    largeur: int = 3,
    log: Callable[[str], None] | None = None,
) -> dict:
    """Applique le plan de rangement :

    - Couples validés -> NNN_pa.png / NNN_po.png dans dossier_tries/
    - Doublons -> supprimés si supprimer_doublons=True, sinon déplacés dans dossier_tries/Doublons/
    - Orphelins (+ couples non retenus) -> dossier_tries/A_verifier/
    - Consigne un journal d'annulation dans .organisation_undo.json
    - Met à jour le cache de signatures
    """
    dest = Path(dossier_tries)
    dest.mkdir(parents=True, exist_ok=True)
    d_doublons = dest / "Doublons"
    d_verif = dest / "A_verifier"
    if not supprimer_doublons:
        d_doublons.mkdir(parents=True, exist_ok=True)
    d_verif.mkdir(parents=True, exist_ok=True)

    def _log(m: str) -> None:
        if log:
            log(m)

    op = shutil.move if deplacer else shutil.copy2
    journal: list[dict[str, str]] = []

    couples_effectifs = (
        plan.couples if couples_selectionnes is None else couples_selectionnes
    )
    set_retenus_po = {c.portrait for c in couples_effectifs}
    couples_recales = [c for c in plan.couples if c.portrait not in set_retenus_po]

    tous_orphelins = list(plan.orphelins)
    for c in couples_recales:
        tous_orphelins.append(c.paysage)
        tous_orphelins.append(c.portrait)

    debut_id = prochain_id(dest)
    total_ids = debut_id + max(len(couples_effectifs) - 1, 0)
    largeur_calc = max(largeur, len(str(total_ids)))

    faits_couples: list[tuple[str, Path, Path]] = []
    for idx, c in enumerate(couples_effectifs):
        num = debut_id + idx
        ident = f"{num:0{largeur_calc}d}"
        pa_dest = dest / f"{ident}_pa.png"
        po_dest = dest / f"{ident}_po.png"

        _transferer_image_png(c.paysage, pa_dest, deplacer=deplacer)
        _transferer_image_png(c.portrait, po_dest, deplacer=deplacer)

        journal.append({"de": str(pa_dest), "vers": str(c.paysage)})
        journal.append({"de": str(po_dest), "vers": str(c.portrait)})
        faits_couples.append((ident, pa_dest, po_dest))

    faits_doublons: list[Path] = []
    for f, _ in plan.doublons:
        if not f.exists():
            continue
        if supprimer_doublons:
            f.unlink()
            faits_doublons.append(f)
        else:
            cible = _cible_sans_ecraser(d_doublons, f.name)
            op(str(f), str(cible))
            journal.append({"de": str(cible), "vers": str(f)})
            faits_doublons.append(cible)

    faits_orphelins: list[Path] = []
    for f in tous_orphelins:
        if not f.exists():
            continue
        cible = _cible_sans_ecraser(d_verif, f.name)
        op(str(f), str(cible))
        journal.append({"de": str(cible), "vers": str(f)})
        faits_orphelins.append(cible)

    _log(
        f"Rangement terminé : {len(faits_couples)} couple(s), "
        f"{len(faits_doublons)} doublon(s), {len(faits_orphelins)} orphelin(s)."
    )

    undo_path = dest / FICHIER_UNDO
    if deplacer:
        undo_path.write_text(
            json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
        )

    charger_signatures_destination(dest, inclure_doublons=True)

    premier_id = faits_couples[0][0] if faits_couples else None
    dernier_id = faits_couples[-1][0] if faits_couples else None

    return {
        "premier_id": premier_id,
        "dernier_id": dernier_id,
        "nb_couples": len(faits_couples),
        "nb_doublons": len(faits_doublons),
        "nb_orphelins": len(faits_orphelins),
        "journal": undo_path if deplacer else None,
    }


def annuler_organisation(dossier_tries: str | Path) -> int:
    """Restaure les fichiers déplacés lors de la dernière organisation.

    Retourne le nombre de fichiers restaurés.
    """
    base = Path(dossier_tries)
    chemin_undo = base / FICHIER_UNDO
    if not chemin_undo.is_file():
        raise FileNotFoundError(f"Aucun journal d'annulation dans {dossier_tries}")

    entrees = json.loads(chemin_undo.read_text(encoding="utf-8"))
    n = 0
    for e in entrees:
        de = Path(e["de"])
        vers = Path(e["vers"])
        if de.exists() and not vers.exists():
            vers.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(de), str(vers))
            n += 1

    chemin_undo.unlink(missing_ok=True)
    charger_signatures_destination(base, inclure_doublons=True)
    return n


# --- Audit d'un dossier déjà trié --------------------------------------------


@dataclass
class Suspect:
    ident: str
    score_propre: int  # inliers entre NNN_po et NNN_pa
    meilleur_ident: str  # paysage qui correspond le mieux au portrait
    meilleur_score: int

    @property
    def probable_erreur(self) -> bool:
        """Le portrait correspond bien mieux à un AUTRE paysage qu'au sien."""
        return (
            self.meilleur_ident != self.ident
            and self.meilleur_score >= 2 * max(self.score_propre, 1)
            and self.meilleur_score >= SEUIL_INLIERS
        )


def auditer(
    dossier_tries: str | Path,
    *,
    seuil_suspect: int = SEUIL_INLIERS,
    log: Callable[[str], None] | None = None,
) -> list[Suspect]:
    """Repère les couples ``NNN_pa``/``NNN_po`` probablement mal classés.

    Optimisation : on calcule d'abord le score « propre » de chaque couple (rapide),
    puis on ne cherche le vrai paysage que pour les couples au score propre faible.
    """
    base = Path(dossier_tries)
    if not base.is_dir():
        raise NotADirectoryError(f"Dossier introuvable : {base}")

    def _log(m: str) -> None:
        if log:
            log(m)

    pa = {f.stem[:-3]: f for f in base.glob("*_pa.*")}
    po = {f.stem[:-3]: f for f in base.glob("*_po.*")}
    ids = sorted(pa.keys() & po.keys())
    if not ids:
        return []

    sift = _moteur_sift()
    _log(f"Descripteurs des {len(ids)} paysages…")
    d_pa = {n: descripteurs(pa[n], sift) for n in ids}

    _log("Score propre de chaque couple…")
    suspects: list[tuple[str, int, object]] = []
    for n in ids:
        dpo = descripteurs(po[n], sift)
        propre = compter_inliers(dpo, d_pa[n])
        if propre < seuil_suspect:
            suspects.append((n, propre, dpo))

    _log(f"{len(suspects)} couple(s) suspect(s) à vérifier en profondeur…")
    resultats: list[Suspect] = []
    for n, propre, dpo in suspects:
        meilleur_n, meilleur_s = n, propre
        for m in ids:
            s = compter_inliers(dpo, d_pa[m])
            if s > meilleur_s:
                meilleur_s, meilleur_n = s, m
        resultats.append(
            Suspect(
                ident=n,
                score_propre=propre,
                meilleur_ident=meilleur_n,
                meilleur_score=meilleur_s,
            )
        )
    # Les erreurs probables d'abord.
    resultats.sort(key=lambda s: (not s.probable_erreur, s.score_propre))
    return resultats


def fichier_pour(dossier: str | Path, ident: str, suffixe: str) -> Path | None:
    """Retrouve le fichier ``<ident>_<suffixe>.*`` (pa/po) d'un dossier trié."""
    for f in sorted(Path(dossier).glob(f"{ident}_{suffixe}.*")):
        return f
    return None


def sauver_audit(suspects: list[Suspect], dossier_tries: str | Path) -> Path:
    """Sauvegarde le résultat d'audit en JSON (pour rechargement sans recalcul)."""
    from dataclasses import asdict

    chemin = Path(dossier_tries) / ".audit_fonds.json"
    chemin.write_text(
        json.dumps([asdict(s) for s in suspects], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return chemin


def charger_audit(dossier_tries: str | Path) -> list[Suspect] | None:
    """Recharge un audit précédent depuis le JSON, ou None s'il n'existe pas."""
    chemin = Path(dossier_tries) / ".audit_fonds.json"
    if not chemin.is_file():
        return None
    data = json.loads(chemin.read_text(encoding="utf-8"))
    return [Suspect(**d) for d in data]


def rapport_html(suspects: list[Suspect], dossier_tries: str | Path) -> str:
    """Construit un rapport HTML : par suspect, portrait + paysage actuel + proposé."""
    base = Path(dossier_tries)

    def img(ident: str, suffixe: str) -> str:
        f = fichier_pour(base, ident, suffixe)
        if not f:
            return '<div class="vide">(manquant)</div>'
        return f'<img src="{f.name}" loading="lazy">'

    cartes = []
    for s in suspects:
        classe = "erreur" if s.probable_erreur else "faible"
        cartes.append(f"""
        <div class="carte {classe}">
          <div class="tete">{s.ident}_po
            {'<span class="tag">erreur probable</span>' if s.probable_erreur else '<span class="tag gris">score faible</span>'}
          </div>
          <div class="trio">
            <figure>{img(s.ident, "po")}<figcaption>portrait {s.ident}_po</figcaption></figure>
            <figure>{img(s.ident, "pa")}<figcaption>paysage actuel {s.ident}_pa<br>score {s.score_propre}</figcaption></figure>
            <figure>{img(s.meilleur_ident, "pa")}<figcaption>proposé {s.meilleur_ident}_pa<br>score {s.meilleur_score}</figcaption></figure>
          </div>
        </div>""")

    nb_err = sum(s.probable_erreur for s in suspects)
    return f"""<!doctype html><html lang="fr"><head><meta charset="utf-8">
<title>Audit Fonds_Tries</title>
<style>
 body{{font-family:system-ui,sans-serif;margin:1.5rem;background:#111;color:#eee}}
 h1{{font-size:1.3rem}} .resume{{color:#aaa;margin-bottom:1rem}}
 .carte{{border:1px solid #333;border-radius:8px;padding:.6rem;margin:.6rem 0;background:#1a1a1a}}
 .carte.erreur{{border-color:#c0392b}} .tete{{font-weight:600;margin-bottom:.4rem}}
 .tag{{background:#c0392b;color:#fff;border-radius:4px;padding:.05rem .4rem;font-size:.75rem;margin-left:.4rem}}
 .tag.gris{{background:#555}}
 .trio{{display:flex;gap:.6rem;flex-wrap:wrap}}
 figure{{margin:0;text-align:center}} img{{height:200px;border-radius:4px;background:#000}}
 figcaption{{font-size:.75rem;color:#bbb;margin-top:.2rem}}
 .vide{{height:200px;display:flex;align-items:center;justify-content:center;color:#888;width:150px;border:1px dashed #444}}
</style></head><body>
<h1>Audit des fonds triés</h1>
<div class="resume">{len(suspects)} couple(s) à score faible, dont <b>{nb_err}</b> erreur(s) probable(s).
Portrait — paysage actuel — paysage proposé. L'audit ne corrige rien : à vérifier à l'œil.</div>
{''.join(cartes)}
</body></html>"""


# --- Déduplication d'un dossier trié (NNN_pa / NNN_po) -----------------------


@dataclass
class PlanDedup:
    gardes: list[str]  # numéros conservés (collection propre)
    doublons: list[Path]  # fichiers redondants → dossier Doublons/
    a_verifier: list[Path]  # images uniques sans partenaire → A_verifier/


def _hash_par_numero(dossier: Path, suffixe: str) -> dict[str, tuple[Path, object]]:
    """{numero: (fichier, phash)} pour tous les ``NNN_<suffixe>.*`` d'un dossier."""
    out: dict[str, tuple[Path, object]] = {}
    for f in sorted(dossier.glob(f"*_{suffixe}.*")):
        num = f.stem[:-3]  # retire "_pa"/"_po"
        try:
            out[num] = (f, _phash(f))
        except Exception:
            continue
    return out


def plan_deduplication(
    dossier_tries: str | Path,
    *,
    suspects: set[str],
    confirmes_ok: set[str] = frozenset(),
    seuil_hash: int = 4,
) -> PlanDedup:
    """Calcule quoi conserver / isoler, sans rien déplacer.

    - Un numéro est un « bon couple » si son ``pa`` s'apparie à son ``po``
      (déduit de l'audit : tout ce qui n'est PAS suspect, plus ``confirmes_ok``).
    - Les bons couples en double (même paysage ET même portrait) → on garde le 1er,
      les copies vont dans **Doublons**.
    - Pour un numéro « cassé » (suspect), chaque image va dans **Doublons** si son
      contenu existe déjà dans un couple conservé, sinon dans **A_verifier** (unique).
    """
    base = Path(dossier_tries)
    pa = _hash_par_numero(base, "pa")
    po = _hash_par_numero(base, "po")
    nums = sorted(set(pa) & set(po))

    suspects = set(suspects) - set(confirmes_ok)

    def proche(h1, h2) -> bool:
        return (h1 - h2) <= seuil_hash

    gardes: list[str] = []
    doublons: list[Path] = []
    a_verifier: list[Path] = []
    kept: list[tuple[object, object, str]] = []  # (pa_hash, po_hash, num)

    for n in nums:
        if n in suspects:
            continue
        ph, oh = pa[n][1], po[n][1]
        if any(proche(ph, kph) and proche(oh, koh) for kph, koh, _ in kept):
            doublons += [pa[n][0], po[n][0]]  # couple entièrement redondant
        else:
            gardes.append(n)
            kept.append((ph, oh, n))

    kept_pa = [kph for kph, _, _ in kept]
    kept_po = [koh for _, koh, _ in kept]

    for n in sorted(suspects):
        for dic, kept_hashes in ((pa, kept_pa), (po, kept_po)):
            if n not in dic:
                continue
            f, h = dic[n]
            if any(proche(h, kh) for kh in kept_hashes):
                doublons.append(f)  # copie redondante d'un contenu conservé
            else:
                a_verifier.append(f)  # image unique orpheline → à revoir

    return PlanDedup(gardes=gardes, doublons=doublons, a_verifier=a_verifier)


def appliquer_deduplication(
    plan: PlanDedup,
    dossier_tries: str | Path,
    *,
    log: Callable[[str], None] | None = None,
) -> Path:
    """Déplace les fichiers du plan vers Doublons/ et A_verifier/, écrit un journal."""
    base = Path(dossier_tries)
    journal: list[dict[str, str]] = []
    for fichiers, sous in (
        (plan.doublons, "Doublons"),
        (plan.a_verifier, "A_verifier"),
    ):
        dest = base / sous
        for f in fichiers:
            if not f.exists():
                continue
            dest.mkdir(parents=True, exist_ok=True)
            cible = dest / f.name
            shutil.move(str(f), str(cible))
            journal.append({"de": str(cible), "vers": str(f)})
        if fichiers and log:
            log(f"{len(fichiers)} fichier(s) → {sous}/")

    chemin = base / ".dedup_undo.json"
    chemin.write_text(
        json.dumps(journal, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return chemin


def annuler_deduplication(dossier_tries: str | Path) -> int:
    """Restaure les fichiers déplacés par la déduplication. Retourne le nb restauré."""
    chemin = Path(dossier_tries) / ".dedup_undo.json"
    if not chemin.is_file():
        raise FileNotFoundError(f"Aucun journal de déduplication dans {dossier_tries}")
    entrees = json.loads(chemin.read_text(encoding="utf-8"))
    n = 0
    for e in entrees:
        de, vers = Path(e["de"]), Path(e["vers"])
        if de.exists() and not vers.exists():
            shutil.move(str(de), str(vers))
            n += 1
    return n


def ranger(
    couples: list[Couple],
    dossier_tries: str | Path,
    *,
    deplacer: bool = True,
    largeur: int = 3,
) -> list[tuple[str, Path, Path]]:
    """Range les couples dans le dossier trié en ``NNN_pa`` / ``NNN_po``.

    :param deplacer: True = déplace (retire de la source) ; False = copie.
    :return: liste de (identifiant, destination_pa, destination_po).
    """
    dest = Path(dossier_tries)
    dest.mkdir(parents=True, exist_ok=True)
    op = shutil.move if deplacer else shutil.copy2

    debut = prochain_id(dest)
    resultats = []
    for k, c in enumerate(couples):
        ident = f"{debut + k:0{largeur}d}"
        pa_dest = dest / f"{ident}_pa{c.paysage.suffix.lower()}"
        po_dest = dest / f"{ident}_po{c.portrait.suffix.lower()}"
        op(str(c.paysage), str(pa_dest))
        op(str(c.portrait), str(po_dest))
        resultats.append((ident, pa_dest, po_dest))
    return resultats
