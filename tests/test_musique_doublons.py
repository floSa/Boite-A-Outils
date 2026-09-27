from pathlib import Path

from tools import musique_doublons as md


def _f(chemin: Path, contenu: str = "x") -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def test_normaliser_titre():
    assert md.normaliser_titre("01 - Karaoke Bar") == "karaoke bar"
    assert (
        md.normaliser_titre("01. Andreas Johnson - Living To Die (2)")
        == "living to die"
    )
    assert md.normaliser_titre("99 Luftballons") == "99 luftballons"
    assert (
        md.normaliser_titre("03) Artiste - Titre avec é accents !")
        == "titre avec e accents"
    )


def test_nom_album_base():
    # Détection des mentions d'éditions entre parenthèses, crochets ou en fin de nom
    assert (
        md.nom_album_base("Doo-Wops & Hooligans (Deluxe Edition)")
        == "Doo-Wops & Hooligans"
    )
    assert (
        md.nom_album_base("Doo-Wops & Hooligans [Extended]") == "Doo-Wops & Hooligans"
    )
    assert md.nom_album_base("Doo-Wops & Hooligans - Deluxe") == "Doo-Wops & Hooligans"
    assert md.nom_album_base("Doo-Wops & Hooligans Deluxe") == "Doo-Wops & Hooligans"
    assert (
        md.nom_album_base("Doo-Wops & Hooligans Deluxe Edition")
        == "Doo-Wops & Hooligans"
    )
    assert (
        md.nom_album_base("Random Access Memories (10th Anniversary Edition)")
        == "Random Access Memories"
    )
    assert md.nom_album_base("Thriller [25th Anniversary]") == "Thriller"
    assert md.nom_album_base("Thriller (Remastered 2021)") == "Thriller"

    # Mots-clés seuls : ne JAMAIS vider le nom si c'est le titre réel de l'album
    assert md.nom_album_base("Deluxe") == "Deluxe"
    assert md.nom_album_base("(Deluxe)") == "Deluxe"
    assert md.nom_album_base("[Deluxe Edition]") == "Deluxe Edition"
    assert md.nom_album_base("Extended") == "Extended"

    # Nom d'album intégrant le mot au milieu (groupe Deluxe)
    assert md.nom_album_base("The Deluxe Family Show") == "The Deluxe Family Show"


def test_detecter_singles_en_album(tmp_path):
    # Artiste 1 : single présent dans un album + single unique
    _f(tmp_path / "ArtisteA" / "Singles" / "Titre Unique.flac", "contenu_unique")
    _f(tmp_path / "ArtisteA" / "Singles" / "Titre Album.flac", "contenu_album")
    _f(tmp_path / "ArtisteA" / "Mon Album" / "01 - Titre Album.flac", "contenu_album")

    doublons = md.detecter_singles_en_album(tmp_path)
    assert len(doublons) == 1
    assert doublons[0].artiste == "ArtisteA"
    assert doublons[0].single_path.name == "Titre Album.flac"
    assert doublons[0].album_nom == "Mon Album"


def test_detecter_pistes_en_double(tmp_path):
    # Album avec collision de nom (2)
    piste_orig = tmp_path / "ArtisteB" / "Album1" / "01 - Chanson.flac"
    piste_double = tmp_path / "ArtisteB" / "Album1" / "01 - Chanson (2).flac"
    _f(piste_orig, "version_1")
    _f(piste_double, "version_2")

    doublons = md.detecter_pistes_en_double(tmp_path)
    assert len(doublons) == 1
    assert doublons[0].album == "Album1"
    assert doublons[0].piste_a_garder.name == "01 - Chanson.flac"
    assert doublons[0].piste_en_trop.name == "01 - Chanson (2).flac"


def test_detecter_albums_similaires(tmp_path):
    # Album Standard (4 titres) vs Deluxe (4 titres communs + 2 bonus)
    for i in range(1, 5):
        _f(tmp_path / "ArtisteC" / "Album Standard" / f"0{i} - Piste {i}.flac")
        _f(tmp_path / "ArtisteC" / "Album Deluxe" / f"0{i} - Piste {i}.flac")
    _f(tmp_path / "ArtisteC" / "Album Deluxe" / "05 - Bonus 1.flac")
    _f(tmp_path / "ArtisteC" / "Album Deluxe" / "06 - Bonus 2.flac")

    # Autre album indépendant (titres complètement différents)
    for i in range(1, 5):
        _f(tmp_path / "ArtisteC" / "Autre Album" / f"0{i} - Autre {i}.flac")

    paires = md.detecter_albums_similaires(tmp_path, seuil_similarite=0.75)
    assert len(paires) == 1
    p = paires[0]
    assert p.artiste == "ArtisteC"
    noms = {p.album_1.name, p.album_2.name}
    assert noms == {"Album Standard", "Album Deluxe"}
    assert p.similarite == 1.0  # 4 / min(4, 6) = 100%
    assert len(p.titres_communs) == 4
    assert len(p.titres_uniques_2) == 2 or len(p.titres_uniques_1) == 2
    assert p.meme_nom_base is True
    assert p.nom_base == "Album"


def test_supprimer_fichiers_et_annuler(tmp_path):
    f1 = tmp_path / "Artiste" / "Singles" / "Doublon.flac"
    _f(f1, "contenu")

    # Mise en corbeille
    nb = md.supprimer_fichiers([f1], tmp_path, corbeille=True)
    assert nb == 1
    assert not f1.exists()

    corbeille = tmp_path / md.NOM_CORBEILLE_DOUBLONS
    assert any(corbeille.rglob("Doublon.flac"))

    # Annulation
    restaures = md.annuler(tmp_path)
    assert restaures == 1
    assert f1.is_file()
