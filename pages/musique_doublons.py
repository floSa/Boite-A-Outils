from pathlib import Path

import pandas as pd
import streamlit as st

from tools.musique_doublons import (
    NOM_CORBEILLE_DOUBLONS,
    NOM_JOURNAL_DOUBLONS,
    annuler,
    detecter_albums_similaires,
    detecter_pistes_en_double,
    detecter_singles_en_album,
    supprimer_album,
    supprimer_fichiers,
)
from ui import champ_dossier

st.title("👯 Gérer les doublons de la bibliothèque")
st.caption(
    "Détecte et traite les doublons dans une arborescence musicale "
    "(singles déjà en album, pistes clonées dans un même album, versions standard vs deluxe)."
)

racine = champ_dossier(
    "Racine de la bibliothèque",
    "musique_doublons_racine",
    valeur_defaut="M:/musiques/__autres",
)

col1, col2 = st.columns(2)
with col1:
    corbeille = st.checkbox(
        f"Déplacer vers la corbeille (`{NOM_CORBEILLE_DOUBLONS}/`) au lieu de supprimer définitivement",
        value=True,
    )
with col2:
    seuil_pct = st.slider(
        "Seuil de similarité pour les albums (ex. 75%)",
        min_value=50,
        max_value=100,
        value=75,
        step=5,
    )

if not racine:
    st.stop()

base = Path(racine)
if not base.is_dir():
    st.error(f"Dossier introuvable : {base}")
    st.stop()

if st.button("🔍 Analyser la bibliothèque", type="primary"):
    barre = st.progress(0.0, text="Analyse des doublons…")

    def _prog(fait: int, total: int) -> None:
        barre.progress(fait / total if total else 1.0, text=f"Artiste {fait}/{total}")

    try:
        doublons_singles = detecter_singles_en_album(base, progress=_prog)
        doublons_pistes = detecter_pistes_en_double(base, progress=_prog)
        doublons_albums = detecter_albums_similaires(
            base, seuil_similarite=seuil_pct / 100.0, progress=_prog
        )
        barre.empty()
        st.session_state["doublons_singles"] = doublons_singles
        st.session_state["doublons_pistes"] = doublons_pistes
        st.session_state["doublons_albums"] = doublons_albums
        st.session_state["doublons_racine"] = str(base)
    except Exception as e:
        barre.empty()
        st.error(f"Erreur lors de l'analyse : {e}")

singles = st.session_state.get("doublons_singles")
pistes = st.session_state.get("doublons_pistes")
albums = st.session_state.get("doublons_albums")

if singles is None or pistes is None or albums is None:
    st.info(
        "Cliquez sur **Analyser la bibliothèque** pour lancer la recherche de doublons."
    )
    st.stop()

base_analyse = Path(st.session_state["doublons_racine"])

tab1, tab2, tab3 = st.tabs(
    [
        f"🎵 Singles en album ({len(singles)})",
        f"👯 Pistes en double ({len(pistes)})",
        f"💿 Albums similaires ({len(albums)})",
    ]
)

# =============================================================================
# Onglet 1 : Singles déjà en album
# =============================================================================
with tab1:
    st.markdown("#### Singles déjà présents dans un album")
    st.caption(
        "Morceaux situés dans `Singles/` qui existent déjà dans l'un des albums de l'artiste. "
        "Le single peut être retiré sans perte de contenu."
    )
    if not singles:
        st.success("Aucun single en double trouvé dans les albums.")
    else:
        df_singles = pd.DataFrame(
            [
                {
                    "Artiste": s.artiste,
                    "Single à supprimer": s.single_path.name,
                    "Album contenant le titre": s.album_nom,
                    "Piste dans l'album": s.album_track_path.name,
                    "Raison": s.raison,
                }
                for s in singles
            ]
        )
        st.dataframe(df_singles, use_container_width=True, hide_index=True)

        libelle = "Déplacer en corbeille" if corbeille else "Supprimer définitivement"
        if st.button(
            f"{libelle} les {len(singles)} single(s) en double", type="primary"
        ):
            chemins = [s.single_path for s in singles]
            nb = supprimer_fichiers(chemins, base_analyse, corbeille=corbeille)
            st.success(f"{nb} single(s) traité(s) avec succès.")
            st.session_state.pop("doublons_singles", None)
            st.rerun()

# =============================================================================
# Onglet 2 : Pistes en double dans un album
# =============================================================================
with tab2:
    st.markdown("#### Pistes en double au sein d'un même album")
    st.caption(
        "Fichiers en double dans le même dossier d'album (collision de renommage `(2)`, "
        "fichiers identiques au bit près ou fusion d'anciennes versions). La meilleure version "
        "est conservée."
    )
    if not pistes:
        st.success("Aucune piste en double détectée dans les albums.")
    else:
        df_pistes = pd.DataFrame(
            [
                {
                    "Artiste": p.artiste,
                    "Album": p.album,
                    "Fichier conservé": p.piste_a_garder.name,
                    "Fichier en trop (à supprimer)": p.piste_en_trop.name,
                    "Raison": p.raison,
                }
                for p in pistes
            ]
        )
        st.dataframe(df_pistes, use_container_width=True, hide_index=True)

        libelle = "Déplacer en corbeille" if corbeille else "Supprimer définitivement"
        if st.button(f"{libelle} les {len(pistes)} piste(s) en double", type="primary"):
            chemins = [p.piste_en_trop for p in pistes]
            nb = supprimer_fichiers(chemins, base_analyse, corbeille=corbeille)
            st.success(f"{nb} piste(s) en double traitée(s) avec succès.")
            st.session_state.pop("doublons_pistes", None)
            st.rerun()

# =============================================================================
# Onglet 3 : Albums similaires / Deluxe
# =============================================================================
with tab3:
    st.markdown("#### Albums similaires d'un même artiste")
    st.caption(
        "Paires d'albums partageant une grande proportion de titres (ex: Standard vs Deluxe). "
        "Comparez les titres et sélectionnez la version à conserver."
    )
    if not albums:
        st.success("Aucune paire d'albums similaires détectée avec ce seuil.")
    else:
        actions_albums: list[tuple[Path, str]] = []
        for idx, p in enumerate(albums):
            badge_base = (
                f" — 🎯 Même album : « {p.nom_base} »" if p.meme_nom_base else ""
            )
            titre_exp = (
                f"[{p.artiste}] « {p.album_1.name} » ↔ « {p.album_2.name} »{badge_base} "
                f"({p.similarite * 100:.0f}% en commun)"
            )
            with st.expander(titre_exp, expanded=False):
                if p.meme_nom_base:
                    st.info(
                        f"🎯 **Éditions du même album** : ces dossiers partagent le nom de base "
                        f"**« {p.nom_base} »** (après nettoyage des crochets, parenthèses et mots-clés d'édition)."
                    )
                c1, c2 = st.columns(2)
                with c1:
                    st.markdown(f"**Album 1 :** `{p.album_1.name}`")
                    st.caption(
                        f"{p.nb_titres_1} titre(s) · {p.taille_1 / (1024 * 1024):.1f} Mo"
                    )
                    if p.titres_uniques_1:
                        st.markdown(
                            f"*Titres exclusifs à Album 1 ({len(p.titres_uniques_1)}) :*"
                        )
                        for t in p.titres_uniques_1:
                            st.write(f"- {t}")
                    else:
                        st.caption("— aucun titre exclusif (inclus dans Album 2) —")

                with c2:
                    st.markdown(f"**Album 2 :** `{p.album_2.name}`")
                    st.caption(
                        f"{p.nb_titres_2} titre(s) · {p.taille_2 / (1024 * 1024):.1f} Mo"
                    )
                    if p.titres_uniques_2:
                        st.markdown(
                            f"*Titres exclusifs à Album 2 ({len(p.titres_uniques_2)}) :*"
                        )
                        for t in p.titres_uniques_2:
                            st.write(f"- {t}")
                    else:
                        st.caption("— aucun titre exclusif (inclus dans Album 1) —")

                st.markdown(f"**Titres en commun ({len(p.titres_communs)}) :**")
                st.caption(
                    ", ".join(p.titres_communs[:15])
                    + ("..." if len(p.titres_communs) > 15 else "")
                )

                choix = st.radio(
                    "Décision pour cette paire :",
                    options=[
                        "Garder les deux (ne rien faire)",
                        f"Garder « {p.album_1.name} » (supprimer « {p.album_2.name} »)",
                        f"Garder « {p.album_2.name} » (supprimer « {p.album_1.name} »)",
                    ],
                    key=f"decision_album_{idx}",
                )
                if choix.startswith(f"Garder « {p.album_1.name} »"):
                    actions_albums.append((p.album_2, p.album_2.name))
                elif choix.startswith(f"Garder « {p.album_2.name} »"):
                    actions_albums.append((p.album_1, p.album_1.name))

        if actions_albums:
            st.divider()
            st.warning(
                f"⚠️ {len(actions_albums)} album(s) sélectionné(s) pour suppression.",
                icon="⚠️",
            )
            libelle = (
                "Déplacer en corbeille" if corbeille else "Supprimer définitivement"
            )
            if st.button(
                f"{libelle} les {len(actions_albums)} album(s) sélectionné(s)",
                type="primary",
            ):
                for alb_path, alb_nom in actions_albums:
                    supprimer_album(alb_path, base_analyse, corbeille=corbeille)
                st.success(f"{len(actions_albums)} album(s) traité(s).")
                st.session_state.pop("doublons_albums", None)
                st.rerun()

# =============================================================================
# Annulation
# =============================================================================
chemin_journal = base / NOM_JOURNAL_DOUBLONS
if chemin_journal.is_file():
    st.divider()
    if st.button("↩️ Annuler les dernières suppressions de doublons"):
        try:
            nb_annule = annuler(base)
            st.success(f"{nb_annule} élément(s) restauré(s) depuis la corbeille.")
            st.session_state.pop("doublons_singles", None)
            st.session_state.pop("doublons_pistes", None)
            st.session_state.pop("doublons_albums", None)
            st.rerun()
        except Exception as e:
            st.error(f"Erreur lors de l'annulation : {e}")
