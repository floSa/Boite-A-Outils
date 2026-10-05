from pathlib import Path

import pandas as pd
import streamlit as st

from tools.musique_regrouper import (
    NOM_CORBEILLE_REGROUPER,
    NOM_JOURNAL_REGROUPER,
    NOM_VARIOUS_ARTISTS_DEFAUT,
    SEUIL_MAJORITAIRE_DEFAUT,
    analyser_regroupement,
    annuler_regroupement,
    appliquer_regroupement,
)
from ui import champ_dossier

st.title("🧩 Regrouper les albums multi-artistes")
st.caption(
    "Détecte les albums dont les morceaux sont disséminés dans des dossiers d'artistes "
    "différents (achats Bandcamp, featurings, compilations). Regroupe l'album chez l'artiste "
    "qui détient le plus de titres, ou dans un dossier « Various Artists » si aucun artiste "
    "n'atteint le seuil minimal."
)

racine = champ_dossier(
    "Racine de la bibliothèque",
    "musique_regrouper_racine",
    valeur_defaut="M:/musiques/__autres",
)

col1, col2 = st.columns(2)
with col1:
    seuil_int = st.slider(
        "Seuil minimal pour l'artiste majoritaire",
        min_value=5,
        max_value=50,
        value=int(SEUIL_MAJORITAIRE_DEFAUT * 100),
        step=5,
        format="%d %%",
        help="Si l'artiste ayant le plus de titres détient au moins ce pourcentage des pistes de l'album, "
        "l'album est regroupé chez lui. Sinon, il bascule vers le dossier de repli.",
    )
    seuil_pct = seuil_int / 100.0

with col2:
    dossier_repli = st.text_input(
        "Dossier de repli (aucun artiste au seuil)",
        value=NOM_VARIOUS_ARTISTS_DEFAUT,
        help="Nom du dossier d'artiste utilisé lorsque les pistes sont trop éparpillées.",
    )

col_opt1, col_opt2 = st.columns(2)
with col_opt1:
    corbeille = st.checkbox(
        f"Déplacer les dossiers vidés vers la corbeille (`{NOM_CORBEILLE_REGROUPER}/`)",
        value=True,
    )
with col_opt2:
    nettoyer_artistes = st.checkbox(
        "Supprimer les dossiers artistes qui deviennent totalement vides",
        value=True,
    )

if not racine:
    st.stop()

base = Path(racine)
if not base.is_dir():
    st.error(f"Dossier introuvable : {base}")
    st.stop()

if st.button("Analyser", type="primary"):
    barre = st.progress(0.0, text="Analyse des dossiers d'artistes…")

    def _prog(fait: int, total: int) -> None:
        barre.progress(fait / total if total else 1.0, text=f"Artiste {fait}/{total}")

    try:
        plan = analyser_regroupement(
            base,
            seuil_pct=seuil_pct,
            dossier_repli=dossier_repli.strip() or NOM_VARIOUS_ARTISTS_DEFAUT,
            progress=_prog,
        )
        barre.empty()
        st.session_state["regrouper_plan"] = plan
        st.session_state["regrouper_racine"] = str(base)
    except Exception as e:
        barre.empty()
        st.error(f"Erreur d'analyse : {e}")
        st.stop()

plan = st.session_state.get("regrouper_plan")
if not plan or st.session_state.get("regrouper_racine") != str(base):
    # Proposer l'annulation si un journal existe déjà
    if (base / NOM_JOURNAL_REGROUPER).is_file():
        st.divider()
        st.info("Un journal d'annulation précédent a été détecté dans ce dossier.")
        if st.button("Annuler le dernier regroupement"):
            nb = annuler_regroupement(base)
            st.success(f"Opération annulée : {nb} élément(s) restauré(s).")
    st.stop()

if not plan.albums:
    st.success("Aucun album segmenté détecté dans cette bibliothèque.")
else:
    st.info(
        f"**{len(plan.albums)}** album(s) segmenté(s) détecté(s) · "
        f"**{len(plan.actions_fichiers)}** fichier(s) à transférer · "
        f"**{len(plan.dossiers_sources_a_nettoyer)}** dossier(s) source(s) à vider."
    )

    lignes_synthese = []
    for alb in plan.albums:
        for art, nb in alb.repartition.items():
            if art != alb.artiste_cible:
                lignes_synthese.append(
                    {
                        "Artiste principal": alb.artiste_cible,
                        "Nom de l'album": alb.nom_album_affiche,
                        "Nombre de morceaux déplacés": nb,
                        "Artiste secondaire": art,
                    }
                )
    st.dataframe(pd.DataFrame(lignes_synthese), use_container_width=True, hide_index=True)

    with st.expander(f"Détail des {len(plan.actions_fichiers)} transferts de fichiers"):
        lignes_transferts = [
            {
                "Fichier source": str(act.source.relative_to(base)),
                "Destination": str(act.destination.relative_to(base)),
                "Statut": "Doublon identique" if act.est_identique_deja_present else "Transfert",
            }
            for act in plan.actions_fichiers
        ]
        st.dataframe(pd.DataFrame(lignes_transferts), use_container_width=True, hide_index=True)

    st.divider()
    st.warning(
        "Cette opération déplace les fichiers vers les dossiers cibles et nettoie les dossiers vidés. "
        "Un journal d'annulation sera créé à la racine.",
        icon="⚠️",
    )

    if st.button(f"Regrouper les {len(plan.albums)} album(s)", type="primary"):
        with st.status("Regroupement en cours…", expanded=True) as status:
            res = appliquer_regroupement(
                plan,
                utiliser_corbeille=corbeille,
                supprimer_artistes_vides=nettoyer_artistes,
                log=lambda m: st.write(m),
            )
            status.update(label="Regroupement terminé ✅", state="complete")

        st.success(
            f"**{res.nb_albums}** album(s) traité(s) · "
            f"**{res.nb_fichiers_deplaces}** fichier(s) déplacé(s) · "
            f"**{res.nb_dossiers_nettoyes}** dossier(s) nettoyé(s)."
        )
        if res.rapport_texte:
            st.session_state["regrouper_rapport"] = res.rapport_texte

        # Nettoyer le plan après exécution
        st.session_state.pop("regrouper_plan", None)

rapport = st.session_state.get("regrouper_rapport")
if rapport:
    st.divider()
    st.markdown("### 📋 Rapport d'exécution détaillé")
    st.text_area("Compte-rendu des déplacements", value=rapport, height=280)
    st.download_button(
        "📥 Télécharger le rapport (.txt)",
        data=rapport,
        file_name="rapport_regroupement.txt",
        mime="text/plain",
    )

st.divider()
if (base / NOM_JOURNAL_REGROUPER).is_file():
    if st.button("Annuler le dernier regroupement"):
        nb = annuler_regroupement(base)
        st.session_state.pop("regrouper_rapport", None)
        st.success(f"Opération annulée : {nb} élément(s) restauré(s).")
