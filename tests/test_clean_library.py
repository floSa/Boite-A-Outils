import pytest

from tools import clean_library as cl


def _f(chemin, contenu="x"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


# --- Règle 1 : nom de dossier d'album ---------------------------------------


@pytest.mark.parametrize(
    "entree, attendu",
    [
        # exemple exact demandé : date + Clean + UPC → nom seul
        ("Derealised (2023) (Clean) [UPC3616849569515]", "Derealised"),
        (
            "Génération(s) Eperdue(s) (2018) (Clean) [UPC5060525433962]",
            "Génération(s) Eperdue(s)",
        ),
        # date suivie d'un suffixe dur → date retirée aussi
        ("Album (2018) (Clean)", "Album"),
        ("Album [2018] [UPC123]", "Album"),
        # suffixes durs seuls → retirés
        ("Album {WEB}", "Album"),
        ("Album (Explicit)", "Album"),
        ("Album (clean)", "Album"),
        # ATTENTION : une date SEULE reste (nouvelle règle)
        ("Album (2018)", "Album (2018)"),
        ("Album [2018]", "Album [2018]"),
        ("Nom [Disk 1]", "Nom [Disk 1]"),
        # nom entièrement « technique » → jamais vidé, conservé tel quel
        ("{Awayland}", "{Awayland}"),
        # parenthèses porteuses de sens préservées
        (
            "Le Patient (Bande Originale du Film)",
            "Le Patient (Bande Originale du Film)",
        ),
        ("X (Deluxe)", "X (Deluxe)"),
        ("Y (Four Tet Remix)", "Y (Four Tet Remix)"),
        ("Génération(s) Eperdue(s)", "Génération(s) Eperdue(s)"),
    ],
)
def test_nettoyer_nom_album(entree, attendu):
    assert cl.nettoyer_nom_album(entree) == attendu


# --- Règle 2 : nom de fichier audio -----------------------------------------


@pytest.mark.parametrize(
    "entree, attendu",
    [
        ("01. Artiste - Titre", "01 - Titre"),
        ("7. Artiste - Titre", "07 - Titre"),
        ("07. Clothilde - 102 - 103", "07 - 102 - 103"),  # découpe au 1er « - »
        ("03) Artiste - Titre", "03 - Titre"),
    ],
)
def test_renommer_piste(entree, attendu):
    assert cl.renommer_piste(entree) == attendu


@pytest.mark.parametrize("entree", ["01 - Titre", "Titre sans numéro", "Intro"])
def test_renommer_piste_non_touche(entree):
    assert cl.renommer_piste(entree) is None


# --- Intégration : previsualiser + appliquer --------------------------------


def _biblio(racine):
    _f(racine / "Artiste" / "Album (2018) (Clean)" / "01. Artiste - Un.flac")
    _f(racine / "Artiste" / "Album (2018) (Clean)" / "02. Artiste - Deux.flac")
    # multi-disques : jamais un single, fichiers internes renommés ; dossier avec
    # une année SEULE → doit rester inchangé (nouvelle règle)
    _f(racine / "Artiste" / "Live [2019]" / "CD 01" / "01. Artiste - A.flac")
    _f(racine / "Artiste" / "Live [2019]" / "CD 02" / "01. Artiste - B.flac")
    # nom de dossier porteur de sens → inchangé
    _f(racine / "Artiste" / "OST (Bande Originale du Film)" / "01 - Thème.flac")
    # dossier ignoré (préfixe _)
    _f(racine / "Artiste" / "_perso" / "05. X - Secret.flac")
    # dossier Singles ignoré
    _f(racine / "Artiste" / "Singles" / "01. Artiste - DejaDansSingles.flac")


def test_previsualiser_albums_et_pistes(tmp_path):
    _biblio(tmp_path)
    plan = cl.previsualiser_nettoyage(tmp_path)

    albums = {r.ancien.name: r.nouveau.name for r in plan.albums}
    assert albums == {"Album (2018) (Clean)": "Album"}
    assert "Live [2019]" not in albums  # année seule → conservée
    assert "OST (Bande Originale du Film)" not in albums  # préservé

    pistes = {r.nouveau.name for r in plan.pistes}
    assert "01 - Un.flac" in pistes and "02 - Deux.flac" in pistes
    # multi-disques : les deux CD sont traités même si le dossier n'est pas renommé
    assert "01 - A.flac" in pistes and "01 - B.flac" in pistes
    # « _perso » et « Singles » ignorés, fichier déjà propre non touché
    assert all("Secret" not in n for n in pistes)
    assert all("DejaDansSingles" not in n for n in pistes)


def test_appliquer_aucune_perte_puis_idempotent(tmp_path):
    _biblio(tmp_path)
    avant = sum(1 for p in tmp_path.rglob("*") if p.is_file())

    plan = cl.previsualiser_nettoyage(tmp_path)
    resultat = cl.appliquer(plan, tmp_path)
    assert resultat.erreurs == []
    assert resultat.nb_renommes > 0

    # le journal ne compte pas comme un fichier audio perdu
    apres = sum(
        1 for p in tmp_path.rglob("*") if p.is_file() and p.suffix in cl.AUDIO_EXT
    )
    avant_audio = avant  # tous les _f ci-dessus sont des .flac
    assert apres == avant_audio

    # résultat attendu sur disque
    assert (tmp_path / "Artiste" / "Album" / "01 - Un.flac").is_file()
    assert (tmp_path / "Artiste" / "Live [2019]" / "CD 01" / "01 - A.flac").is_file()
    assert (
        tmp_path / "Artiste" / "OST (Bande Originale du Film)" / "01 - Thème.flac"
    ).is_file()

    # seconde passe : 0 action
    plan2 = cl.previsualiser_nettoyage(tmp_path)
    assert not plan2


def test_annuler_restaure(tmp_path):
    _biblio(tmp_path)
    plan = cl.previsualiser_nettoyage(tmp_path)
    cl.appliquer(plan, tmp_path)
    n = cl.annuler(tmp_path)
    assert n > 0
    assert (
        tmp_path / "Artiste" / "Album (2018) (Clean)" / "01. Artiste - Un.flac"
    ).is_file()


def test_pas_ecrasement_collision(tmp_path):
    # Deux dossiers qui se nettoient vers le même nom cible « Album ».
    _f(tmp_path / "Artiste" / "Album (Clean)" / "01. A - X.flac")
    _f(tmp_path / "Artiste" / "Album [UPC123]" / "01. A - Y.flac")
    plan = cl.previsualiser_nettoyage(tmp_path)
    cl.appliquer(plan, tmp_path)
    noms = {p.name for p in (tmp_path / "Artiste").iterdir()}
    assert "Album" in noms and "Album (2)" in noms  # suffixe, pas d'écrasement
