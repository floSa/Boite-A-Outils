from pathlib import Path

from tools import musique


def _f(chemin: Path, contenu: str = "x"):
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def _biblio(racine: Path):
    _f(racine / "ArtisteA" / "Album1" / "track.flac")          # single + cover (jetée)
    _f(racine / "ArtisteA" / "Album1" / "cover.jpg")
    _f(racine / "ArtisteA" / "Album2" / "01 - Ring Ring.mp3")  # numéro (séparateur)
    _f(racine / "ArtisteA" / "Paroles" / "01 Escapism.flac")   # numéro zéro-paddé + annexe
    _f(racine / "ArtisteA" / "Paroles" / "Cover.jpg")          # image → jetée
    _f(racine / "ArtisteA" / "Paroles" / "lyrics.lrc")         # non-image → déplacé
    _f(racine / "ArtisteA" / "AlbumComplet" / "01.flac")       # vrai album → ignoré
    _f(racine / "ArtisteA" / "AlbumComplet" / "02.flac")
    _f(racine / "ArtisteA" / "AvecDossier" / "hit.flac")       # sous-dossier → à vérifier
    _f(racine / "ArtisteA" / "AvecDossier" / "bonus" / "x.flac")
    _f(racine / "ArtisteB" / "AlbumX" / "song.flac")
    _f(racine / "ArtisteB" / "AlbumX" / "front.png")


def test_titre_sans_numero():
    assert musique._titre_sans_numero("01 - Ring Ring") == "Ring Ring"
    assert musique._titre_sans_numero("07. Titre") == "Titre"
    assert musique._titre_sans_numero("01 Escapism") == "Escapism"
    assert musique._titre_sans_numero("Sans numero") == "Sans numero"
    assert musique._titre_sans_numero("99 Luftballons") == "99 Luftballons"
    assert musique._titre_sans_numero("7 Years") == "7 Years"


def test_analyser_classement(tmp_path):
    _biblio(tmp_path)
    plan = musique.analyser(tmp_path)
    traites = {sa.album.name for sa in plan.a_traiter}
    verifier = {sa.album.name for sa in plan.a_verifier}
    assert traites == {"Album1", "Album2", "Paroles", "AlbumX"}
    assert verifier == {"AvecDossier"}
    assert "AlbumComplet" not in traites | verifier


def test_previsualiser_numero_et_annexe(tmp_path):
    _biblio(tmp_path)
    plan = musique.analyser(tmp_path)
    par_dst = {mv.audio_dst.name: mv for mv in musique.previsualiser(plan)}
    assert "Ring Ring.mp3" in par_dst
    assert "Escapism.flac" in par_dst
    # le .lrc (non-image) est déplacé, renommé au titre ; la .jpg non
    annexes = [dst.name for _, dst in par_dst["Escapism.flac"].annexes]
    assert annexes == ["Escapism.lrc"]


def test_previsualiser_collision_meme_artiste(tmp_path):
    _f(tmp_path / "Art" / "A" / "same.flac")
    _f(tmp_path / "Art" / "B" / "same.flac")
    plan = musique.analyser(tmp_path)
    noms = sorted(mv.audio_dst.name for mv in musique.previsualiser(plan))
    assert noms == ["same (2).flac", "same.flac"]


def test_appliquer_titre_et_annexe_images_jetees(tmp_path):
    _biblio(tmp_path)

    plan = musique.analyser(tmp_path)
    res = musique.appliquer(plan, tmp_path)
    assert res.erreurs == []

    singA = tmp_path / "ArtisteA" / "Singles"
    assert (singA / "track.flac").is_file()
    assert (singA / "Ring Ring.mp3").is_file()
    assert (singA / "Escapism.flac").is_file()
    assert (singA / "Escapism.lrc").is_file()  # non-image déplacé + renommé
    # les images NE sont PAS dans Singles
    assert not (singA / "cover.jpg").exists()
    assert not (singA / "Escapism.jpg").exists()

    # Aucun dossier corbeille parasite n'est créé dans la musique
    assert not (tmp_path / musique.NOM_CORBEILLE).exists()
    # Les dossiers albums vidés sont supprimés
    assert not (tmp_path / "ArtisteA" / "Album1").exists()
    assert not (tmp_path / "ArtisteA" / "Paroles").exists()

    # Vrai album et « à vérifier » laissés en place
    assert (tmp_path / "ArtisteA" / "AlbumComplet").is_dir()
    assert (tmp_path / "ArtisteA" / "AvecDossier").is_dir()

    # Le journal d'annulation est créé côté application
    assert res.journal.is_file()


def test_annuler_restaure(tmp_path):
    _biblio(tmp_path)
    plan = musique.analyser(tmp_path)
    musique.appliquer(plan, tmp_path)
    musique.annuler(tmp_path)
    # Les fichiers audio et annexes sont restaurés dans leurs dossiers d'origine
    assert (tmp_path / "ArtisteA" / "Album1" / "track.flac").is_file()
    assert (tmp_path / "ArtisteA" / "Paroles" / "01 Escapism.flac").is_file()
    assert (tmp_path / "ArtisteA" / "Paroles" / "lyrics.lrc").is_file()
    assert (tmp_path / "ArtisteB" / "AlbumX" / "song.flac").is_file()

