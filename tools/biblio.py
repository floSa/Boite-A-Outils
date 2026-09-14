"""Outils de catalogage : tri de cotes de bibliothèque (type Dewey musique)."""

from __future__ import annotations

import csv
import io
import re
from dataclasses import dataclass
from pathlib import Path


@dataclass
class Entree:
    artiste: str
    album: str
    cote: str
    brut: str


# Statuts fréquents de disponibilité en bibliothèque à éliminer de la cote pure
_STATUT_MOTS = (
    "prêt",
    "pret",
    "dispo",
    "rayon",
    "retour",
    "réserv",
    "reserv",
    "magasin",
    "voir",
    "consultation",
    "perdu",
    "exclu",
)

_STATUT_PARENTHESES = re.compile(
    r"\s*\((?:En rayon|Prêt[ée]?|Pret[ée]?|Disponible|En réserve|En reserve|Consultation|Exclu|Non prêtable|Perdu)[^)]*\)",
    re.IGNORECASE,
)

_STATUT_FIN = re.compile(
    r"\s*-\s*(?:Prêt[ée]?|Pret[ée]?|Disponible|En rayon|Voir dispo).*$",
    re.IGNORECASE,
)


def nettoyer_cote(cote_brute: str) -> str:
    """Nettoie une cote de bibliothèque en retirant les statuts de disponibilité et mentions parasites.

    Exemples :
        '780.2 KNI (En rayon)' -> '780.2 KNI'
        '782.42-AIR - Prêté jusqu'au 12/03/2026' -> '782.42-AIR'
        '782.ARC 61 (Prêté)' -> '782.ARC 61'
        'D 59179 (En réserve)' -> 'D 59179'
        'LA002499 (Consultation sur place)' -> 'LA002499'
        '780.2 KNI - Disponible' -> '780.2 KNI'
    """
    if not cote_brute:
        return ""
    cote = str(cote_brute).strip()

    # 1. Retrait des parenthèses de statut
    cote = _STATUT_PARENTHESES.sub("", cote)

    # 2. Découpage sur " - " si la seconde partie est un statut de prêt
    if " - " in cote:
        parties = [p.strip() for p in cote.split(" - ")]
        if len(parties) >= 2 and any(
            parties[1].lower().startswith(m) for m in _STATUT_MOTS
        ):
            cote = parties[0].strip()

    # 3. Retrait des mentions textuelles de fin orphelines
    cote = _STATUT_FIN.sub("", cote)

    # Normalisation des espaces internes
    return re.sub(r"\s+", " ", cote).strip()


# Une cote commence par un chiffre (Dewey, ex. "786.1 PIN") OU par un court
# préfixe de lettres (1 à 6, archives, ex. "D 500", "LA002499") immédiatement
# suivi d'un chiffre — pas un titre d'album quelconque.
_COTE_LETTRES_CHIFFRES = re.compile(r"^[A-Za-zÀ-ÿ]{1,6}\.?\s*\d")


def _ressemble_a_une_cote(segment: str) -> bool:
    propre = nettoyer_cote(segment)
    return bool(re.match(r"\d", propre) or _COTE_LETTRES_CHIFFRES.match(propre))


def parser_lignes(texte: str) -> list[Entree]:
    """Parse des lignes ``Artiste - Album - Cote``.

    La cote est le dernier segment s'il ressemble à une cote (commence par un
    chiffre, ex. ``786.1 PIN``, ou par un court préfixe de lettres suivi de
    chiffres, ex. ``D 500``). Les mentions de statut de prêt (ex. ``(En rayon)``,
    ``- Prêté``) sont automatiquement nettoyées pour isoler la cote pure.
    Sinon l'entrée est conservée sans cote (triée en fin).
    """
    entrees: list[Entree] = []
    for ligne in texte.splitlines():
        ligne = ligne.strip()
        if not ligne:
            continue
        parts = [p.strip() for p in ligne.split(" - ")]
        if len(parts) >= 2 and _ressemble_a_une_cote(parts[-1]):
            artiste = parts[0]
            cote = nettoyer_cote(parts[-1])
            album = " - ".join(parts[1:-1])
        elif (
            len(parts) >= 3
            and _ressemble_a_une_cote(parts[-2])
            and any(parts[-1].lower().startswith(m) for m in _STATUT_MOTS)
        ):
            # Cas d'un statut séparé par un " - " supplémentaire : Artiste - Album - Cote - Statut
            artiste = parts[0]
            cote = nettoyer_cote(parts[-2])
            album = " - ".join(parts[1:-2])
        else:
            artiste = parts[0]
            album = " - ".join(parts[1:])
            cote = ""
        brut = " - ".join(p for p in (artiste, album, cote) if p)
        entrees.append(Entree(artiste=artiste, album=album, cote=cote, brut=brut))
    return entrees


_ENTETE_CSV = {"artiste,album,cote", "artiste;album;cote"}


def parser_texte(texte: str) -> list[Entree]:
    """Parse des lignes ``Artiste - Album - Cote`` OU ``Artiste, Album, Cote``,
    séparateur détecté ligne par ligne (espaces superflus retirés autour de
    chaque champ). Une éventuelle ligne d'en-tête ``Artiste,Album,Cote`` est
    ignorée. Pratique pour un copier-coller depuis un tableur, quel que soit
    le séparateur utilisé.
    """
    entrees: list[Entree] = []
    for ligne in texte.splitlines():
        brut = ligne.strip()
        if not brut:
            continue
        if brut.lower().replace(" ", "") in _ENTETE_CSV:
            continue
        if " - " in brut:
            entrees.extend(parser_lignes(brut))
            continue
        if "," in brut:
            parts = [p.strip() for p in brut.split(",")]
            if len(parts) >= 2 and _ressemble_a_une_cote(parts[-1]):
                artiste = parts[0]
                cote = nettoyer_cote(parts[-1])
                album = ", ".join(parts[1:-1])
            else:
                artiste = parts[0]
                album = ", ".join(parts[1:])
                cote = ""
            brut_propre = " - ".join(p for p in (artiste, album, cote) if p)
            entrees.append(
                Entree(artiste=artiste, album=album, cote=cote, brut=brut_propre)
            )
            continue
        entrees.append(Entree(artiste=brut, album="", cote="", brut=brut))
    return entrees


def parser_csv(texte: str) -> list[Entree]:
    """Parse un CSV à colonnes ``Artiste``, ``Album``, ``Cote`` (cote facultative).

    Les en-têtes sont reconnus sans tenir compte de la casse ni des espaces.
    Une ligne sans cote est conservée (utile pour vérifier l'existence
    artiste/album et récupérer la cote actuelle, sans en connaître une au
    départ).
    """
    lecteur = csv.DictReader(io.StringIO(texte))
    entetes = {(nom or "").strip().lower(): nom for nom in (lecteur.fieldnames or [])}
    col_artiste = entetes.get("artiste")
    col_album = entetes.get("album")
    col_cote = entetes.get("cote")
    if col_artiste is None or col_album is None:
        raise ValueError(
            "Le CSV doit contenir au moins les colonnes « Artiste » et « Album » "
            "(« Cote » facultative)."
        )

    entrees: list[Entree] = []
    for ligne in lecteur:
        artiste = (ligne.get(col_artiste) or "").strip()
        album = (ligne.get(col_album) or "").strip()
        cote = nettoyer_cote(ligne.get(col_cote) or "") if col_cote else ""
        if not artiste and not album:
            continue
        brut = " - ".join(p for p in (artiste, album, cote) if p)
        entrees.append(Entree(artiste=artiste, album=album, cote=cote, brut=brut))
    return entrees


def extraire_colonne_artistes(df) -> list[str]:
    """Extrait la colonne « Artiste » d'un tableau (DataFrame pandas), une entrée par ligne.

    En-tête reconnu sans tenir compte de la casse (``artiste`` ou ``artistes``).
    Les cellules vides sont ignorées ; une cellule peut contenir plusieurs noms
    séparés par des virgules (ex. ``"Synapson,Tim Dup,Lass"``) — c'est à
    l'appelant de les rechercher séparément, cette fonction les renvoie tels quels.
    """
    colonnes = {str(c).strip().lower(): c for c in df.columns}
    col = colonnes.get("artiste") or colonnes.get("artistes")
    if col is None:
        raise ValueError("Le fichier doit contenir une colonne « Artiste ».")
    valeurs = df[col].dropna().astype(str).str.strip()
    return [v for v in valeurs if v]


_COTE_NUM = re.compile(r"\d+")


def _cle_cote(e: Entree) -> tuple[int, str, float, str]:
    """Clé de tri à 3 niveaux, pour ne jamais comparer les nombres comme du texte
    (sinon "D 9179" > "D 61385" à tort : '9' > '6' au premier caractère) :

    0. Cote Dewey (commence par un chiffre, ex. ``786.1 KNI``) : triée par sa
       valeur numérique.
    1. Cote « lettres + chiffres » (archives, ex. ``D 59179``, ``LA002499``) :
       groupée par préfixe de lettres, puis triée numériquement dans ce préfixe.
    2. Cote sans aucun chiffre, ou absente : en fin de liste, alphabétique.
    """
    cote = nettoyer_cote(e.cote)
    if not cote:
        return (2, "", 0.0, "")

    m_dewey = re.match(r"(\d+(?:\.\d+)?)\s*(.*)", cote)
    if m_dewey:
        return (0, "", float(m_dewey.group(1)), m_dewey.group(2).lower())

    m_num = _COTE_NUM.search(cote)
    if m_num:
        prefixe = cote[: m_num.start()].strip().lower()
        reste = cote[m_num.end() :].strip().lower()
        return (1, prefixe, float(m_num.group()), reste)

    return (2, cote.lower(), 0.0, "")


def trier_par_cote(entrees: list[Entree]) -> list[Entree]:
    """Trie les entrées par cote croissante (numérique puis alphabétique)."""
    return sorted(entrees, key=_cle_cote)


def formater(entrees: list[Entree]) -> str:
    """Reconstruit le texte trié, une entrée par ligne."""
    return "\n".join(e.brut for e in entrees)


def trier_fichier(chemin: str | Path, sortie: str | Path | None = None) -> Path:
    """Lit un fichier de cotes, le trie et l'écrit (par défaut, écrase la source)."""
    src = Path(chemin)
    entrees = trier_par_cote(parser_lignes(src.read_text(encoding="utf-8")))
    cible = Path(sortie) if sortie else src
    cible.write_text(formater(entrees) + "\n", encoding="utf-8")
    return cible
