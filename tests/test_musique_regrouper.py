from pathlib import Path

from tools import musique_regrouper as mr


def _f(chemin: Path, contenu: str = "x") -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def test_normaliser_nom_album():
    assert mr.normaliser_nom_album("Mon Album") == "mon album"
    assert mr.normaliser_nom_album("  Mon   Album  ") == "mon album"
    assert mr.normaliser_nom_album("DÉJÀ VU") == "deja vu"
    assert mr.normaliser_nom_album("Éponyme - 2024") == "eponyme - 2024"
    assert mr.normaliser_nom_album("Bande–Originale") == "bande-originale"


def test_album_non_segmente_ignore(tmp_path):
    # Un album présent uniquement sous un seul artiste ne doit pas être touché
    _f(tmp_path / "ArtisteA" / "Album Unique" / "01 - Titre 1.flac", "audio1")
    _f(tmp_path / "ArtisteA" / "Album Unique" / "02 - Titre 2.flac", "audio2")

    plan = mr.analyser_regroupement(tmp_path)
    assert len(plan.albums) == 0
    assert len(plan.actions_fichiers) == 0


def test_singles_ignores(tmp_path):
    # Le dossier Singles ne doit pas être considéré comme un album
    _f(tmp_path / "ArtisteA" / "Singles" / "01 - Single 1.flac", "s1")
    _f(tmp_path / "ArtisteB" / "Singles" / "02 - Single 2.flac", "s2")

    plan = mr.analyser_regroupement(tmp_path)
    assert len(plan.albums) == 0


def test_regroupement_vers_artiste_majoritaire(tmp_path):
    # Album "Split Album" avec 3 titres chez ArtisteA et 1 titre chez ArtisteB
    # ArtisteA détient 3/4 = 75% (>= 20%) -> Cible = ArtisteA
    _f(tmp_path / "ArtisteA" / "Split Album" / "01 - Titre 1.flac", "t1")
    _f(tmp_path / "ArtisteA" / "Split Album" / "02 - Titre 2.flac", "t2")
    _f(tmp_path / "ArtisteA" / "Split Album" / "03 - Titre 3.flac", "t3")
    _f(tmp_path / "ArtisteB" / "Split Album" / "04 - Titre 4.flac", "t4")
    _f(tmp_path / "ArtisteB" / "Split Album" / "cover.jpg", "image")

    plan = mr.analyser_regroupement(tmp_path, seuil_pct=0.20)
    assert len(plan.albums) == 1
    album = plan.albums[0]
    assert album.artiste_cible == "ArtisteA"
    assert not album.est_repli_various
    assert album.total_pistes == 4
    assert album.repartition == {"ArtisteA": 3, "ArtisteB": 1}

    # Application du regroupement
    res = mr.appliquer_regroupement(plan, utiliser_corbeille=True, supprimer_artistes_vides=True)
    assert res.nb_albums == 1
    assert res.nb_fichiers_deplaces == 2  # 04 - Titre 4.flac + cover.jpg
    assert res.nb_doublons_ignores == 0
    assert not res.erreurs

    # Vérification sur disque
    dossier_cible = tmp_path / "ArtisteA" / "Split Album"
    assert (dossier_cible / "01 - Titre 1.flac").is_file()
    assert (dossier_cible / "02 - Titre 2.flac").is_file()
    assert (dossier_cible / "03 - Titre 3.flac").is_file()
    assert (dossier_cible / "04 - Titre 4.flac").is_file()
    assert (dossier_cible / "cover.jpg").is_file()

    # Le dossier source de l'album sous ArtisteB a été déplacé en corbeille
    assert not (tmp_path / "ArtisteB" / "Split Album").exists()
    assert (tmp_path / "_albums_vides_a_supprimer" / "ArtisteB" / "Split Album").is_dir()

    # Test d'annulation
    nb_annules = mr.annuler_regroupement(tmp_path)
    assert nb_annules > 0
    assert (tmp_path / "ArtisteB" / "Split Album" / "04 - Titre 4.flac").is_file()
    assert (tmp_path / "ArtisteB" / "Split Album" / "cover.jpg").is_file()
    assert not (tmp_path / "_albums_vides_a_supprimer").exists()


def test_regroupement_repli_various_artists_quand_aucun_atteint_seuil(tmp_path):
    # 6 artistes distincts, 1 titre chacun.
    # Chaque artiste a 1/6 = 16.67% < 20%
    # -> Cible = Various Artists
    artistes = ["Artiste1", "Artiste2", "Artiste3", "Artiste4", "Artiste5", "Artiste6"]
    for i, art in enumerate(artistes, 1):
        _f(tmp_path / art / "Compil Bandcamp" / f"0{i} - Titre.flac", f"contenu_{i}")

    plan = mr.analyser_regroupement(tmp_path, seuil_pct=0.20, dossier_repli="Various Artists")
    assert len(plan.albums) == 1
    album = plan.albums[0]
    assert album.artiste_cible == "Various Artists"
    assert album.est_repli_various
    assert album.total_pistes == 6

    # Appliquer
    res = mr.appliquer_regroupement(plan, utiliser_corbeille=False, supprimer_artistes_vides=True)
    assert res.nb_fichiers_deplaces == 6
    assert not res.erreurs

    dossier_cible = tmp_path / "Various Artists" / "Compil Bandcamp"
    assert dossier_cible.is_dir()
    fichiers_finaux = list(dossier_cible.glob("*.flac"))
    assert len(fichiers_finaux) == 6

    # Les artistes d'origine sont désormais vidés et supprimés
    for art in artistes:
        assert not (tmp_path / art).exists()


def test_gestion_collision_et_doublon_binaire(tmp_path):
    # Collision de nom de fichier lors du regroupement :
    # 1. Doublon binaire identique -> ignoré/supprimé de la source
    # 2. Fichier avec nom identique mais contenu différent -> suffixe (2)
    _f(tmp_path / "ArtisteA" / "Mon Album" / "01 - Titre.flac", "audio_identique")
    _f(tmp_path / "ArtisteA" / "Mon Album" / "02 - Titre.flac", "audio_different_A")

    _f(tmp_path / "ArtisteB" / "Mon Album" / "01 - Titre.flac", "audio_identique")
    _f(tmp_path / "ArtisteB" / "Mon Album" / "02 - Titre.flac", "audio_different_B")

    plan = mr.analyser_regroupement(tmp_path)
    res = mr.appliquer_regroupement(plan, utiliser_corbeille=True)

    dossier_cible = tmp_path / "ArtisteA" / "Mon Album"
    # Le fichier identique n'a pas été dupliqué
    assert (dossier_cible / "01 - Titre.flac").read_text(encoding="utf-8") == "audio_identique"
    assert not (dossier_cible / "01 - Titre (2).flac").exists()

    # Le fichier différent a été renommé sans écraser l'original
    assert (dossier_cible / "02 - Titre.flac").read_text(encoding="utf-8") == "audio_different_A"
    assert (dossier_cible / "02 - Titre (2).flac").read_text(encoding="utf-8") == "audio_different_B"
