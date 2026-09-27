"""Boîte à outils — point d'entrée Streamlit.

Lancer avec :  uv run streamlit run app.py
"""

import streamlit as st

st.set_page_config(page_title="Boîte à outils", page_icon="🧰", layout="wide")


def page(chemin, titre, icone):
    return st.Page(f"pages/{chemin}", title=titre, icon=icone)


accueil = st.Page("pages/accueil.py", title="Accueil", icon="🏠", default=True)

sections = {
    "🎵 Audio": [
        page("audio_flac.py", "Convertir en FLAC", "💿"),
        page("audio_normaliser.py", "Normaliser des FLAC", "🎚️"),
        page("audio_convertir.py", "Convertir un format", "🔁"),
        page("audio_extraire.py", "Extraire l'audio d'une vidéo", "🎵"),
        page("audio_decouper.py", "Découper", "✂️"),
        page("audio_volume.py", "Normaliser le volume", "🔊"),
        page("audio_renommer.py", "Renommer depuis les tags", "🏷️"),
        page("audio_tags.py", "Éditer les tags en masse", "🏷️"),
    ],
    "🖼️ Images": [
        page("images_redimensionner.py", "Redimensionner / compresser", "📐"),
        page("images_convertir.py", "Convertir de format", "🔄"),
        page("images_doublons.py", "Trouver les doublons", "👯"),
        page("images_renumeroter.py", "Renuméroter", "🔢"),
        page("fonds_organiser.py", "Organiser les fonds d'écran", "🖼️"),
        page("images_filigrane.py", "Filigrane", "💧"),
    ],
    "🎬 Vidéo": [
        page("video_telecharger.py", "Télécharger depuis le web", "📥"),
        page("video_merge.py", "Fusionner", "🎬"),
        page("video_decouper.py", "Découper", "✂️"),
        page("video_compresser.py", "Compresser", "🗜️"),
        page("video_convertir.py", "Convertir", "🔄"),
        page("video_images.py", "Extraire des images", "🖼️"),
        page("video_gif.py", "Créer un GIF", "🎞️"),
    ],
    "📄 PDF": [
        page("pdf_extract.py", "Extraire des pages", "✂️"),
        page("pdf_fusionner.py", "Fusionner", "📚"),
        page("pdf_pages.py", "Supprimer / pivoter des pages", "🔧"),
        page("pdf_images.py", "Images ↔ PDF", "🖼️"),
        page("pdf_compresser.py", "Compresser", "🗜️"),
        page("pdf_securite.py", "Protéger / déprotéger", "🔒"),
        page("pdf_texte.py", "Extraire le texte", "📝"),
        page("pdf_filigrane.py", "Filigrane", "💧"),
    ],
    "📁 Fichiers": [
        page("files_clean.py", "Nettoyer les noms", "🧹"),
        page("files_remplacer.py", "Renommer en masse", "🔁"),
        page("files_csv.py", "Renommer depuis un CSV", "📋"),
        page("files_doublons.py", "Fichiers en double", "🧬"),
        page("files_ranger.py", "Ranger automatiquement", "🗂️"),
        page("files_stats.py", "Statistiques", "📊"),
        page("files_comparer.py", "Comparer deux dossiers", "🔀"),
        page("files_arborescence.py", "Arborescence → Excel", "🌳"),
        page("files_html_md.py", "HTML → Markdown", "🌐"),
    ],
    "🔤 Données": [
        page("data_convertir.py", "Convertir un tableau", "🔀"),
        page("data_lignes.py", "Nettoyer des lignes", "📃"),
    ],
    "🗣️ Voix & langues": [
        page("tts_lire.py", "Lire du texte à voix haute", "🔊"),
        page("traduction_traduire.py", "Traduire un texte", "🌐"),
        page("transcription_transcrire.py", "Transcrire un audio / une vidéo", "🎙️"),
    ],
    "🎼 Bibliothèque perso": [
        page("musique_catalogue.py", "Catalogue de la bibliothèque", "🎵"),
        page("musique_nettoyer.py", "Uniformiser les noms", "🧼"),
        page("musique_singles.py", "Regrouper les singles", "🎼"),
    ],
    "📚 Bibliothèque municipale": [
        page("biblio_cotes.py", "Trier des cotes", "📇"),
        page("biblio_dispo.py", "Vérifier la disponibilité BM Lyon", "📗"),
        page("biblio_artistes.py", "Récolter les CD d'artistes", "🎧"),
    ],
}

toutes_les_pages = [accueil] + [p for pages in sections.values() for p in pages]
navigation = st.navigation(toutes_les_pages, position="hidden")

with st.sidebar:
    st.page_link(accueil)
    for titre_section, pages in sections.items():
        # La section de la page affichée reste ouverte : sinon tout se replie à
        # chaque navigation et on perd sa place.
        section_courante = any(p is navigation for p in pages)
        with st.expander(titre_section, expanded=section_courante):
            for p in pages:
                st.page_link(p)

navigation.run()
