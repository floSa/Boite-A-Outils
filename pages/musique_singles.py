from pathlib import Path

import pandas as pd
import streamlit as st

from tools.musique import (
    analyser,
    annuler,
    appliquer,
    chemin_journal_singles,
    previsualiser,
)
from ui import champ_dossier

st.title("🎼 Regrouper les singles")
st.caption(
    "Parcourt une bibliothèque (racine → artistes → albums) et regroupe chaque album "
    "à un seul titre dans un dossier `Singles/` par artiste (numéro de piste retiré, "
    "pochettes déplacées). Le dossier vidé n'est **pas supprimé** : il part dans "
    f"`{NOM_CORBEILLE}/`, à supprimer d'un clic ensuite. Rien n'est perdu."
)

st.info(
    "💡 **Ordre conseillé** : il est recommandé d'exécuter d'abord **Uniformiser les noms** "
    "avant de regrouper les singles. Ainsi, les métadonnées parasites et les éventuels préfixes "
    "d'artiste dans les pistes (`01. Artiste - Titre` → `01 - Titre`) sont assainis avant le retrait "
    "du numéro de piste et le transfert dans `Singles/`."
)

racine = champ_dossier(
    "Dossier racine de la bibliothèque",
    "musique_singles_racine",
    placeholder="M:/musiques",
)

if st.button("Analyser", type="primary"):
    base = Path(racine)
    if not base.is_dir():
        st.error(f"Dossier introuvable : {base}")
        st.stop()
    barre = st.progress(0.0, text="Analyse de l'arborescence…")

    def _prog(fait, total):
        barre.progress(fait / total if total else 1.0, text=f"Artiste {fait}/{total}")

    st.session_state["singles_plan"] = analyser(base, progress=_prog)
    st.session_state["singles_racine"] = str(base)
    barre.empty()

plan = st.session_state.get("singles_plan")
if not plan:
    st.stop()

racine = st.session_state["singles_racine"]
st.success(
    f"{len(plan.a_traiter)} single(s) à regrouper · "
    f"{len(plan.a_verifier)} dossier(s) à vérifier (laissés tels quels)."
)

if plan.a_traiter:
    st.markdown("#### À regrouper")
    mouvements = previsualiser(plan)
    lignes = []
    for sa, mv in zip(plan.a_traiter, mouvements):
        lignes.append(
            {
                "Artiste": sa.artiste.name,
                "Album (→ corbeille)": sa.album.name,
                "Titre → Singles/": mv.audio_dst.name,
                "Fichiers annexes (→ Singles)": len(mv.annexes),
            }
        )
    st.dataframe(pd.DataFrame(lignes), use_container_width=True, hide_index=True)

if plan.a_verifier:
    with st.expander(f"⚠️ {len(plan.a_verifier)} dossier(s) à vérifier (non traités)"):
        for sa in plan.a_verifier:
            extras = ", ".join(p.name for p in sa.autres)
            st.write(
                f"- `{sa.artiste.name}/{sa.album.name}` — contenu en plus : {extras}"
            )

st.divider()
if plan.a_traiter:
    st.warning(
        "L'opération **déplace** les fichiers. Aucun fichier n'est supprimé : les "
        f"dossiers vidés partent dans `{NOM_CORBEILLE}/`. Un journal d'annulation est créé.",
        icon="⚠️",
    )
    if st.button(f"Regrouper {len(plan.a_traiter)} single(s)", type="primary"):
        with st.status("Déplacement…", expanded=True) as status:
            res = appliquer(plan, racine, log=lambda m: st.write(m))
            status.update(label="Terminé ✅", state="complete")
        st.success(
            f"{res.nb_singles} single(s) regroupé(s), {res.nb_en_corbeille} dossier(s) "
            f"en corbeille. Journal : `{res.journal.name}`"
        )
        if res.erreurs:
            with st.expander(f"⚠️ {len(res.erreurs)} erreur(s)"):
                for e in res.erreurs:
                    st.write(f"- {e}")
        st.session_state.pop("singles_plan", None)

if chemin_journal_singles(racine).is_file():
    st.divider()
    if st.button("↩️ Annuler le dernier regroupement"):
        n = annuler(racine)
        st.success(f"{n} action(s) annulée(s).")
