from tools.audio import nom_depuis_tags


def test_nom_depuis_tags_piste_paddee():
    tags = {"piste": "3", "artiste": "Daft Punk", "titre": "Aerodynamic"}
    assert (
        nom_depuis_tags(tags, "{piste} - {artiste} - {titre}")
        == "03 - Daft Punk - Aerodynamic"
    )


def test_nom_depuis_tags_champ_manquant():
    tags = {"piste": "", "artiste": "Air", "titre": ""}
    # champs vides tolérés, pas de KeyError
    assert nom_depuis_tags(tags, "{artiste} - {titre}").startswith("Air")


def test_nom_depuis_tags_nettoie_caracteres():
    tags = {"artiste": "AC/DC", "titre": "T.N.T."}
    out = nom_depuis_tags(tags, "{artiste} - {titre}")
    assert "/" not in out  # slash retiré (illégal dans un nom de fichier)


def test_inventaire_non_flac(tmp_path):
    from tools.audio import inventaire_non_flac

    (tmp_path / "song1.mp3").write_text("dummy", encoding="utf-8")
    (tmp_path / "song2.wav").write_text("dummy", encoding="utf-8")
    (tmp_path / "song3.flac").write_text("dummy", encoding="utf-8")
    (tmp_path / "cover.jpg").write_text("dummy", encoding="utf-8")
    (tmp_path / "notes.txt").write_text("dummy", encoding="utf-8")

    sub = tmp_path / "sub"
    sub.mkdir()
    (sub / "song4.m4a").write_text("dummy", encoding="utf-8")
    (sub / "ignored.flac").write_text("dummy", encoding="utf-8")

    # Récursif
    res = inventaire_non_flac(tmp_path, recursif=True)
    noms = [f.name for f in res]
    assert sorted(noms) == ["song1.mp3", "song2.wav", "song4.m4a"]

    # Non récursif
    res_non_rec = inventaire_non_flac(tmp_path, recursif=False)
    noms_non_rec = [f.name for f in res_non_rec]
    assert sorted(noms_non_rec) == ["song1.mp3", "song2.wav"]


def test_convertir_en_flac_remplacement(tmp_path):
    from tools.audio import convertir_en_flac
    from tools.ffmpeg_utils import lancer_ffmpeg

    mp3 = tmp_path / "test_piste.mp3"
    lancer_ffmpeg(
        [
            "-f",
            "lavfi",
            "-i",
            "sine=frequency=1000:duration=0.2",
            "-c:a",
            "libmp3lame",
            str(mp3),
        ]
    )
    assert mp3.is_file()

    flac = convertir_en_flac(mp3, remplacer=True)
    assert flac.is_file()
    assert flac.suffix == ".flac"
    assert flac.stat().st_size > 0
    # Le fichier MP3 d'origine a été supprimé (remplacé)
    assert not mp3.exists()


def test_convertir_dossier_flac(tmp_path):
    from tools.audio import convertir_dossier_flac
    from tools.ffmpeg_utils import lancer_ffmpeg

    pistes = []
    for i in (1, 2):
        p = tmp_path / f"track{i}.mp3"
        lancer_ffmpeg(
            [
                "-f",
                "lavfi",
                "-i",
                "sine=frequency=800:duration=0.2",
                "-c:a",
                "libmp3lame",
                str(p),
            ]
        )
        pistes.append(p)

    res = convertir_dossier_flac(pistes, remplacer=True)
    assert len(res.convertis) == 2
    assert res.erreurs == []
    for src, dst in res.convertis:
        assert not src.exists()
        assert dst.is_file()
        assert dst.suffix == ".flac"
