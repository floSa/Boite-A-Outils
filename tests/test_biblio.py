import pandas as pd
import pytest

from tools import biblio


def test_parser_csv_complet():
    txt = "Artiste,Album,Cote\nCliff Martinez,The Knick,786.1 KNI 3\nGaëtan Roussel,Ginger,780.65 ROU\n"
    entrees = biblio.parser_csv(txt)
    assert [e.artiste for e in entrees] == ["Cliff Martinez", "Gaëtan Roussel"]
    assert entrees[0].album == "The Knick"
    assert entrees[0].cote == "786.1 KNI 3"


def test_parser_csv_entetes_insensibles_casse():
    txt = "ARTISTE , Album \nDanny Elfman,Alice\n"
    [e] = biblio.parser_csv(txt)
    assert e.artiste == "Danny Elfman"
    assert e.album == "Alice"


def test_parser_csv_sans_cote_conserve():
    txt = "Artiste,Album\nDanny Elfman,Alice\n"
    [e] = biblio.parser_csv(txt)
    assert e.cote == ""
    assert e.brut == "Danny Elfman - Alice"


def test_parser_csv_colonnes_manquantes():
    with pytest.raises(ValueError):
        biblio.parser_csv("Titre,Auteur\nX,Y\n")


def test_extraire_colonne_artistes():
    df = pd.DataFrame({"Artiste": ["Fakear", "  ", "Synapson,Tim Dup,Lass", None]})
    assert biblio.extraire_colonne_artistes(df) == ["Fakear", "Synapson,Tim Dup,Lass"]


def test_extraire_colonne_artistes_entete_insensible_casse():
    df = pd.DataFrame({"ARTISTES": ["Fakear"], "Album": ["Sauvage"]})
    assert biblio.extraire_colonne_artistes(df) == ["Fakear"]


def test_extraire_colonne_artistes_colonne_absente():
    df = pd.DataFrame({"Nom": ["Fakear"]})
    with pytest.raises(ValueError):
        biblio.extraire_colonne_artistes(df)


def test_parser_cote_simple():
    [e] = biblio.parser_lignes("Cliff Martinez - The Knick - 786.1 KNI 3")
    assert e.artiste == "Cliff Martinez"
    assert e.album == "The Knick"
    assert e.cote == "786.1 KNI 3"


def test_parser_album_avec_tiret():
    [e] = biblio.parser_lignes("Ahmed Malek - Musique originale. 2 - 786.2 MAL")
    assert e.album == "Musique originale. 2"
    assert e.cote == "786.2 MAL"


def test_parser_sans_cote():
    [e] = biblio.parser_lignes("Anne - Sophie Versnaeyen - La belle époque")
    assert e.cote == ""


def test_tri_par_cote_numerique():
    txt = (
        "B - Album - 786.11 DAN\n"
        "A - Album - 786.1 KNI\n"
        "C - Album - 786.2 MAL\n"
        "Z - Album - 786 BO"
    )
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    cotes = [e.cote for e in tries]
    assert cotes == ["786 BO", "786.1 KNI", "786.11 DAN", "786.2 MAL"]


def test_sans_cote_va_en_fin():
    txt = "A - X - 786.1 KNI\nB - Y - pas de cote"
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    assert tries[-1].artiste == "B"


def test_trier_fichier(tmp_path):
    f = tmp_path / "cotes.txt"
    f.write_text("B - X - 786.2 MAL\nA - Y - 786.1 KNI\n", encoding="utf-8")
    biblio.trier_fichier(f)
    assert f.read_text(encoding="utf-8").splitlines()[0].endswith("786.1 KNI")


def test_tri_cote_lettres_puis_chiffres_numerique_pas_alphabetique():
    # Régression : comparer "D 9179" et "D 61385" comme du TEXTE les classerait
    # dans le mauvais ordre ('9' > '6' au premier caractère). Le tri doit être
    # numérique dans le préfixe de lettres.
    txt = "A - X - D 61385\nB - Y - D 9179\nC - Z - D 500"
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    assert [e.cote for e in tries] == ["D 500", "D 9179", "D 61385"]


def test_tri_cote_dewey_avant_lettres():
    txt = "A - X - D 100\nB - Y - 786.1 KNI"
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    assert tries[0].cote == "786.1 KNI"
    assert tries[1].cote == "D 100"


def test_tri_cote_prefixes_differents_groupes_separement():
    txt = "A - X - LA002499\nB - Y - D 500"
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    # "d" < "la" alphabétiquement : le préfixe D passe avant LA.
    assert [e.cote for e in tries] == ["D 500", "LA002499"]


# --- parser_texte (dash OU virgule, détecté ligne par ligne) --------------------


def test_parser_texte_tirets():
    [e] = biblio.parser_texte("Cliff Martinez - The Knick - 786.1 KNI 3")
    assert e.artiste == "Cliff Martinez"
    assert e.album == "The Knick"
    assert e.cote == "786.1 KNI 3"


def test_parser_texte_virgules():
    [e] = biblio.parser_texte("Cliff Martinez, The Knick, 786.1 KNI 3")
    assert e.artiste == "Cliff Martinez"
    assert e.album == "The Knick"
    assert e.cote == "786.1 KNI 3"


def test_parser_texte_espaces_superflus_retires():
    [e] = biblio.parser_texte("  Cliff Martinez  ,  The Knick  ,  786.1 KNI 3  ")
    assert e.artiste == "Cliff Martinez"
    assert e.album == "The Knick"
    assert e.cote == "786.1 KNI 3"


def test_parser_texte_mixte_tirets_et_virgules():
    txt = "Cliff Martinez - The Knick - 786.1 KNI 3\nFakear, Sauvage, 784.FAK 51"
    entrees = biblio.parser_texte(txt)
    assert [e.artiste for e in entrees] == ["Cliff Martinez", "Fakear"]
    assert [e.cote for e in entrees] == ["786.1 KNI 3", "784.FAK 51"]


def test_parser_texte_entete_ignoree():
    txt = "Artiste,Album,Cote\nFakear,Sauvage,784.FAK 51"
    [e] = biblio.parser_texte(txt)
    assert e.artiste == "Fakear"


def test_parser_texte_virgule_sans_cote():
    [e] = biblio.parser_texte("Fakear, Sauvage")
    assert e.artiste == "Fakear"
    assert e.album == "Sauvage"
    assert e.cote == ""


# --- Tests spécifiques d'épuration stricte des cotes BM Lyon ---


@pytest.mark.parametrize(
    "brute, attendue",
    [
        ("780.2 KNI (En rayon)", "780.2 KNI"),
        ("782.42-AIR - Prêté jusqu'au 12/03/2026", "782.42-AIR"),
        ("782.ARC 61 (Prêté)", "782.ARC 61"),
        ("D 59179 (En réserve)", "D 59179"),
        ("LA002499 (Consultation sur place)", "LA002499"),
        ("780.2 KNI - Disponible", "780.2 KNI"),
        ("786.1 PIN", "786.1 PIN"),
        ("782.42-AIR", "782.42-AIR"),
        ("", ""),
    ],
)
def test_nettoyer_cote(brute, attendue):
    assert biblio.nettoyer_cote(brute) == attendue


def test_parser_lignes_avec_statut_parentheses():
    txt = "Cliff Martinez - The Knick - 786.1 KNI 3 (En rayon)"
    [e] = biblio.parser_lignes(txt)
    assert e.artiste == "Cliff Martinez"
    assert e.album == "The Knick"
    assert e.cote == "786.1 KNI 3"
    assert e.brut == "Cliff Martinez - The Knick - 786.1 KNI 3"


def test_parser_lignes_avec_statut_tiret_supplementaire():
    txt = "Air - Moon Safari - 782.42-AIR - Prêté jusqu'au 15/04/2026"
    [e] = biblio.parser_lignes(txt)
    assert e.artiste == "Air"
    assert e.album == "Moon Safari"
    assert e.cote == "782.42-AIR"
    assert e.brut == "Air - Moon Safari - 782.42-AIR"


def test_tri_cotes_avec_statuts_parasites():
    txt = (
        "A - Album 1 - 786.1 KNI 3 (En rayon)\n"
        "B - Album 2 - 782.42-AIR - Prêté\n"
        "C - Album 3 - D 59179 (En réserve)\n"
        "D - Album 4 - D 9179"
    )
    tries = biblio.trier_par_cote(biblio.parser_lignes(txt))
    assert [e.cote for e in tries] == [
        "782.42-AIR",
        "786.1 KNI 3",
        "D 9179",
        "D 59179",
    ]
