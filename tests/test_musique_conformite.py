"""Tests unitaires pour l'outil de conformité des téléchargements musicaux."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from tools.musique_conformite import (
    BilanConformite,
    PisteAudioInfo,
    analyser_conformite_bibliotheque,
    isoler_quarantaine,
    verifier_album,
)


def test_verifier_album_conforme(tmp_path: Path):
    dossier_album = tmp_path / "Artiste1" / "Album1"
    dossier_album.mkdir(parents=True)

    # Créer de faux fichiers flac
    piste1 = dossier_album / "01 - Piste.flac"
    piste2 = dossier_album / "02 - Piste.flac"
    piste1.write_bytes(b"dummy audio 1")
    piste2.write_bytes(b"dummy audio 2")

    with patch("tools.musique_conformite.mutagen.File") as mock_mutagen:
        mock_audio = MagicMock()
        mock_audio.info.length = 210.0  # 3m30
        mock_mutagen.return_value = mock_audio

        bilan = verifier_album(dossier_album, artiste="Artiste1")

        assert bilan is not None
        assert bilan.est_conforme is True
        assert bilan.nb_pistes == 2
        assert bilan.nb_extraits == 0
        assert bilan.nb_corrompues == 0


def test_verifier_album_extraits_30s(tmp_path: Path):
    dossier_album = tmp_path / "Artiste2" / "Album_Preview"
    dossier_album.mkdir(parents=True)

    piste1 = dossier_album / "01 - Extrait1.flac"
    piste2 = dossier_album / "02 - Extrait2.flac"
    piste1.write_bytes(b"dummy preview 1")
    piste2.write_bytes(b"dummy preview 2")

    with patch("tools.musique_conformite.mutagen.File") as mock_mutagen:
        mock_audio = MagicMock()
        mock_audio.info.length = 30.0  # 30 secondes
        mock_mutagen.return_value = mock_audio

        bilan = verifier_album(dossier_album, artiste="Artiste2")

        assert bilan is not None
        assert bilan.est_conforme is False
        assert bilan.nb_pistes == 2
        assert bilan.nb_extraits == 2
        assert "extraits de preview" in bilan.motif_non_conforme.lower()


def test_isoler_quarantaine(tmp_path: Path):
    racine = tmp_path / "Biblio"
    dossier_album = racine / "Artiste3" / "Album_Rejet"
    dossier_album.mkdir(parents=True)

    piste = dossier_album / "01 - Extrait.flac"
    piste.write_bytes(b"dummy preview")

    bilan_album = verifier_album(dossier_album, artiste="Artiste3")
    # Forcer non conforme pour le test
    bilan_album.est_conforme = False
    bilan_album.motif_non_conforme = "Test rejet"

    bilan_biblio = BilanConformite(
        racine=racine,
        albums_conformes=[],
        albums_non_conformes=[bilan_album],
    )

    dossier_q = tmp_path / "Quarantaine"
    deplaces = isoler_quarantaine(bilan_biblio, dossier_q)

    assert len(deplaces) == 1
    assert not dossier_album.exists()
    assert (dossier_q / "Artiste3" / "Album_Rejet" / "01 - Extrait.flac").exists()
