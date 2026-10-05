from pathlib import Path

from tools import musique_transferer as mt


def _f(chemin: Path, contenu: str = "x") -> None:
    chemin.parent.mkdir(parents=True, exist_ok=True)
    chemin.write_text(contenu, encoding="utf-8")


def test_valider_structure_conforme(tmp_path):
    source = tmp_path / "SourceValide"
    _f(source / "ArtisteA" / "Album 1" / "01 - Track.flac", "audio1")
    _f(source / "ArtisteA" / "Album 2" / "01 - Track.flac", "audio2")
    _f(source / "ArtisteB" / "Album Un" / "01 - Track.flac", "audio3")

    st = mt.valider_structure_source(source)
    assert st.est_valide
    assert st.nb_artistes == 2
    assert st.nb_albums == 3
    assert st.nb_fichiers == 3
    assert not st.anomalies


def test_valider_structure_invalide_fichiers_racine(tmp_path):
    source = tmp_path / "SourceInvalideRacine"
    _f(source / "01 - Orphelin.flac", "audio_racine")
    _f(source / "ArtisteA" / "Album 1" / "01 - Track.flac", "audio1")

    st = mt.valider_structure_source(source)
    assert not st.est_valide
    assert any("directement à la racine" in a for a in st.anomalies)


def test_valider_structure_invalide_orphelin_sous_artiste(tmp_path):
    source = tmp_path / "SourceInvalideArtiste"
    _f(source / "ArtisteA" / "01 - Orphelin.flac", "audio_artiste")
    _f(source / "ArtisteA" / "Album 1" / "01 - Track.flac", "audio1")

    st = mt.valider_structure_source(source)
    assert not st.est_valide
    assert any("hors d'un album" in a for a in st.anomalies)


def test_transfert_multi_sources_et_suppression(tmp_path):
    src1 = tmp_path / "Import1"
    src2 = tmp_path / "Import2"
    dest = tmp_path / "Bibliotheque"
    dest.mkdir(parents=True, exist_ok=True)

    _f(src1 / "ArtisteA" / "Album 1" / "01 - Track.flac", "audio1")
    _f(src2 / "ArtisteB" / "Album 2" / "02 - Track.flac", "audio2")

    plan = mt.preparer_transfert([src1, src2], dest)
    assert plan.peut_executer
    assert len(plan.tous_fichiers) == 2
    assert len(plan.collisions) == 0

    res = mt.executer_transfert_robocopy(plan)
    assert res.succes
    assert res.nb_fichiers_copies == 2
    assert not res.erreurs

    # Vérification que la destination contient les fichiers
    assert (dest / "ArtisteA" / "Album 1" / "01 - Track.flac").is_file()
    assert (dest / "ArtisteB" / "Album 2" / "02 - Track.flac").is_file()

    # Vérification que les sources ont été supprimées
    assert not src1.exists()
    assert not src2.exists()

    # Vérification que le journal en mémoire contient les informations
    assert "ArtisteA" in res.journal_json
    assert "ArtisteB" in res.journal_texte
