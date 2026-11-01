from pathlib import Path

import pandas as pd
import streamlit as st

from tools.musique_conformite import (
    SEUIL_DUREE_EXTRAIT_SEC,
    SEUIL_RATIO_EXTRAIT,
    analyser_conformite_bibliotheque,
    isoler_quarantaine,
)
from ui import champ_dossier

st.title("🛡️ Conformité des Téléchargements & Albums Incomplets")
st.caption(
    "Détecte et bloque les albums non conformes (téléchargements Qobuz échoués contenant "
    "uniquement des extraits de 30 secondes, ou fichiers audio corrompus)."
)

st.markdown("""
### Règle des 30 secondes (Extraits / Previews Qobuz) :
- Analyse la durée réelle de chaque piste via `mutagen`.
- Si $\ge 70\\%$ des pistes d'un album durent $\\le 35$ secondes (ou toutes les pistes), l'album est considéré comme un aperçu incomplet.
- **Action de sécurité :** Ces albums sont isolés en quarantaine et ne sont jamais transférés sur le NAS.
""")

racine = champ_dossier(
    "Dossier source à vérifier",
    "musique_conformite_racine",
    valeur_defaut="C:/Users/FLORIAN/Music/__QBDLX_Download",
)

col1, col2 = st.columns(2)
with col1:
    seuil_sec = st.number_input(
        "Seuil max durée extrait (secondes)",
        min_value=10.0,
        max_value=90.0,
        value=SEUIL_DUREE_EXTRAIT_SEC,
        step=5.0,
    )
with col2:
    seuil_ratio = st.slider(
        "Seuil ratio extraits pour rejet",
        min_value=0.10,
        max_value=1.00,
        value=SEUIL_RATIO_EXTRAIT,
        step=0.05,
        format="%.0f%%",
    )

if st.button("Vérifier la conformité", type="primary"):
    base = Path(racine)
    if not base.is_dir():
        st.error(f"Dossier introuvable : {base}")
        st.stop()

    barre = st.progress(0.0, text="Audit de la durée et intégrité des pistes…")

    def _prog(fait: int, total: int):
        barre.progress(fait / total if total else 1.0, text=f"Artiste {fait}/{total}")

    bilan = analyser_conformite_bibliotheque(
        base,
        seuil_duree=seuil_sec,
        seuil_ratio=seuil_ratio,
        progress=_prog,
    )
    barre.empty()

    st.session_state["conformite_bilan"] = bilan
    st.session_state["conformite_racine"] = str(base)

bilan = st.session_state.get("conformite_bilan")
if bilan is not None:
    st.write("---")
    st.subheader("📊 Bilan du contrôle de conformité")

    c1, c2, c3 = st.columns(3)
    c1.metric("Albums conformes", len(bilan.albums_conformes))
    c2.metric(
        "Albums non conformes (Extraits/Erreurs)", len(bilan.albums_non_conformes)
    )
    c3.metric("Pistes corrompues", bilan.total_pistes_corrompues)

    if bilan.albums_non_conformes:
        st.error(
            f"⚠️ **{len(bilan.albums_non_conformes)} album(s) non conforme(s)** détecté(s) ! "
            "Ces albums ne doivent pas être transférés sur le NAS."
        )

        lignes = []
        for alb in bilan.albums_non_conformes:
            lignes.append(
                {
                    "Artiste": alb.artiste,
                    "Album": alb.album,
                    "Total pistes": alb.nb_pistes,
                    "Extraits (<= 35s)": alb.nb_extraits,
                    "Ratio": f"{alb.ratio_extraits:.0%}",
                    "Motif": alb.motif_non_conforme,
                }
            )
        df_rejet = pd.DataFrame(lignes)
        st.dataframe(df_rejet, use_container_width=True)

        if st.button(
            "🚨 Déplacer les albums non conformes en quarantaine", type="primary"
        ):
            dossier_q = (
                Path(st.session_state["conformite_racine"]) / "_quarantaine_incomplets"
            )
            deplaces = isoler_quarantaine(bilan, dossier_q)
            st.success(
                f"✅ {len(deplaces)} album(s) déplacé(s) avec succès dans : `{dossier_q}`"
            )
            # Réinitialiser le bilan après déplacement
            del st.session_state["conformite_bilan"]
            st.rerun()
    else:
        st.success(
            "🎉 Tous les albums analysés sont conformes et complets ! Prêts pour l'étape suivante."
        )
