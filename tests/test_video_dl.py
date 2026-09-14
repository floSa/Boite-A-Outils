"""Tests unitaires pour tools.video_dl."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from tools.video_dl import formater_duree, recuperer_infos, telecharger_video


def test_formater_duree():
    assert formater_duree(None) == "Inconnue"
    assert formater_duree(45) == "00:45"
    assert formater_duree(65) == "01:05"
    assert formater_duree(3665) == "01:01:05"


def test_recuperer_infos_url_vide():
    with pytest.raises(ValueError, match="vide"):
        recuperer_infos("")


@patch("tools.video_dl.yt_dlp.YoutubeDL")
def test_recuperer_infos_succes(mock_ydl_cls):
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance
    mock_instance.extract_info.return_value = {
        "title": "Vidéo test",
        "uploader": "Auteur test",
        "duration": 120,
        "thumbnail": "https://example.com/thumb.jpg",
        "description": "Description test",
    }

    infos = recuperer_infos("https://www.youtube.com/watch?v=12345")
    assert infos["titre"] == "Vidéo test"
    assert infos["auteur"] == "Auteur test"
    assert infos["duree_secondes"] == 120
    assert infos["duree_formatee"] == "02:00"
    assert infos["miniature"] == "https://example.com/thumb.jpg"


def test_telecharger_video_dossier_invalide(tmp_path: Path):
    dossier_inexistant = tmp_path / "introuvable"
    with pytest.raises(NotADirectoryError):
        telecharger_video("https://example.com/video", dossier_inexistant)


def test_telecharger_video_qualite_invalide(tmp_path: Path):
    with pytest.raises(ValueError, match="Qualité non reconnue"):
        telecharger_video("https://example.com/video", tmp_path, qualite="inconnue")


@patch("tools.video_dl.chemin_ffmpeg")
@patch("tools.video_dl.yt_dlp.YoutubeDL")
def test_telecharger_video_video_hd(mock_ydl_cls, mock_ffmpeg, tmp_path: Path):
    mock_ffmpeg.return_value = "/bin/ffmpeg"
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance

    fichier_simule = tmp_path / "ma_video.mp4"
    fichier_simule.write_bytes(b"dummy mp4")

    mock_instance.extract_info.return_value = {"title": "ma_video", "ext": "mp4"}
    mock_instance.prepare_filename.return_value = str(fichier_simule)

    res = telecharger_video(
        "https://www.youtube.com/watch?v=test",
        tmp_path,
        qualite="meilleure",
    )

    assert res == fichier_simule
    assert res.exists()

    # Vérification des options passées à YoutubeDL
    args_opts = mock_ydl_cls.call_args[0][0]
    assert args_opts["ffmpeg_location"] == "/bin/ffmpeg"
    assert args_opts["merge_output_format"] == "mp4"
    assert "bestvideo+bestaudio/best" in args_opts["format"]


@patch("tools.video_dl.chemin_ffmpeg")
@patch("tools.video_dl.yt_dlp.YoutubeDL")
def test_telecharger_video_audio(mock_ydl_cls, mock_ffmpeg, tmp_path: Path):
    mock_ffmpeg.return_value = "/bin/ffmpeg"
    mock_instance = MagicMock()
    mock_ydl_cls.return_value.__enter__.return_value = mock_instance

    fichier_mp3 = tmp_path / "musique.mp3"
    fichier_mp3.write_bytes(b"dummy mp3")

    mock_instance.extract_info.return_value = {"title": "musique", "ext": "webm"}
    mock_instance.prepare_filename.return_value = str(tmp_path / "musique.webm")

    res = telecharger_video(
        "https://www.youtube.com/watch?v=audio_test",
        tmp_path,
        qualite="audio",
    )

    assert res == fichier_mp3
    assert res.exists()

    # Vérification des options audio
    args_opts = mock_ydl_cls.call_args[0][0]
    assert args_opts["ffmpeg_location"] == "/bin/ffmpeg"
    assert any(
        p.get("key") == "FFmpegExtractAudio"
        for p in args_opts.get("postprocessors", [])
    )
