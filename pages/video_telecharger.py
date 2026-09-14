"""Page Streamlit : Télécharger une vidéo depuis une URL web (YouTube, Facebook, etc.)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import streamlit as st

from tools.video_dl import recuperer_infos, telecharger_video
from ui import champ_dossier, normaliser

st.title("📥 Télécharger depuis le web")
st.caption(
    "Récupère une vidéo depuis YouTube, Facebook, Dailymotion, Instagram, TikTok, etc. "
    "et l'enregistre à l'emplacement de votre choix sur votre machine."
)

url = st.text_input(
    "Lien de la vidéo (URL)",
    placeholder="https://www.youtube.com/watch?v=... ou Facebook, Instagram, Dailymotion...",
    key="video_dl_url",
)

dossier_cible = champ_dossier(
    "Dossier de destination",
    "video_dl_destination",
)

col_opt1, col_opt2 = st.columns([1, 1])
with col_opt1:
    choix_qualite = st.selectbox(
        "Format & Qualité",
        options=[
            "Meilleure qualité disponible",
            "Vidéo 1080p max",
            "Vidéo 720p max",
            "Audio seul (MP3)",
        ],
        index=0,
    )

with col_opt2:
    nom_perso = st.text_input(
        "Nom du fichier (optionnel)",
        placeholder="Laisser vide pour utiliser le titre de la vidéo",
        help="Nom sans extension. Si laissé vide, le titre officiel de la vidéo sera utilisé.",
    )

map_qualite = {
    "Meilleure qualité disponible": "meilleure",
    "Vidéo 1080p max": "1080p",
    "Vidéo 720p max": "720p",
    "Audio seul (MP3)": "audio",
}

# Aperçu optionnel des informations de la vidéo
if url.strip():
    with st.expander("ℹ️ Prévisualiser les informations de la vidéo", expanded=False):
        if st.button("Charger les informations"):
            with st.spinner("Récupération des métadonnées…"):
                try:
                    infos = recuperer_infos(url)
                    col_mini, col_details = st.columns([1, 2])
                    if infos.get("miniature"):
                        with col_mini:
                            st.image(infos["miniature"], use_container_width=True)
                    with col_details:
                        st.subheader(infos.get("titre", "Sans titre"))
                        st.markdown(f"**Auteur :** {infos.get('auteur')}")
                        st.markdown(f"**Durée :** {infos.get('duree_formatee')}")
                except Exception as e:
                    st.error(f"Impossible de lire les informations : {e}")

st.divider()

if not url.strip():
    st.info("Collez l'URL de votre vidéo ci-dessus pour lancer le téléchargement.")
    st.stop()

if not dossier_cible:
    st.warning("Veuillez sélectionner un dossier de destination.")
    st.stop()

chemin_normalise = Path(normaliser(dossier_cible))
if not chemin_normalise.is_dir():
    st.error(f"Le dossier de destination n'existe pas : `{dossier_cible}`")
    st.stop()

if st.button("🚀 Lancer le téléchargement", type="primary", use_container_width=True):
    barre = st.progress(0.0, text="Initialisation du téléchargement…")

    def _progression(d: dict[str, Any]) -> None:
        if d.get("status") == "downloading":
            total = d.get("total_bytes") or d.get("total_bytes_estimate")
            deja = d.get("downloaded_bytes", 0)
            if total and total > 0:
                fraction = min(1.0, max(0.0, deja / total))
                vitesse = d.get("speed")
                vitesse_str = f"{vitesse / 1e6:.1f} Mo/s" if vitesse else "-- Mo/s"
                barre.progress(
                    fraction,
                    text=f"Téléchargement : {fraction * 100:.1f} % ({vitesse_str})",
                )
            else:
                barre.progress(0.5, text="Téléchargement en cours…")
        elif d.get("status") == "finished":
            barre.progress(1.0, text="Finalisation et conversion audio/vidéo…")

    try:
        fichier_telecharge = telecharger_video(
            url.strip(),
            chemin_normalise,
            qualite=map_qualite[choix_qualite],
            nom_fichier=nom_perso.strip() if nom_perso.strip() else None,
            progression=_progression,
        )

        taille_mo = fichier_telecharge.stat().st_size / (1024 * 1024)
        barre.empty()
        st.success(
            f"✅ Téléchargement terminé avec succès !\n\n"
            f"**Fichier :** `{fichier_telecharge.name}` ({taille_mo:.2f} Mo)\n"
            f"**Dossier :** `{dossier_cible}`"
        )

        if fichier_telecharge.suffix.lower() == ".mp3":
            st.audio(str(fichier_telecharge))
        elif fichier_telecharge.suffix.lower() in (".mp4", ".mkv", ".webm"):
            st.video(str(fichier_telecharge))

    except Exception as err:
        barre.empty()
        st.error(f"Une erreur est survenue lors du téléchargement : {err}")
