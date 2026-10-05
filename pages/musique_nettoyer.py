from pathlib import Path

import pandas as pd
import streamlit as st

from tools.clean_library import (
    annuler,
    appliquer,
    chemin_journal_nettoyage,
    previsualiser_nettoyage,
)
from ui import champ_dossier

st.title("🧼 Uniformiser les noms")
st.caption("Structure attendue : `Artiste / Album / Titres`. Cet outil :")
st.markdown("""
- **Nettoie les noms de dossiers d'album** en retirant les suffixes techniques
  parasites en fin de nom :
    - `(Clean)`, `(Explicit)`, `[UPC…]`, `{WEB}` → toujours retirés
    - une année qui les précède est retirée aussi :
      `Derealised (2023) (Clean) [UPC…]` → `Derealised`
    - **mais une date ou un tome seul est conservé** : `Nom (2023)` reste
      `Nom (2023)`, `Nom [Disk 1]` reste `Nom [Disk 1]`
    - les mentions porteuses de sens restent : `(Deluxe)`,
      `(Bande Originale du Film)`…
- **Renomme les fichiers audio** `01. Artiste - Titre` → `01 - Titre`
  (retire l'artiste, garde le n° de piste et le titre).
- **Ne touche à rien d'autre** : aucun tag lu, aucun fichier supprimé, aucun
  dossier supprimé. Les « singles » sont gérés par l'outil dédié
  **Regrouper les singles**.

Rien n'est modifié tant que tu n'as pas cliqué **Appliquer** : l'analyse ne fait
qu'afficher ce qui changerait. Un journal permet d'annuler après coup.
""")

st.info(
    "💡 **Ordre conseillé** : appliquez cet outil (**Uniformiser les noms**) **en premier**, "
    "puis lancez ensuite **Regrouper les singles**. De cette manière, les noms d'albums sont nettoyés "
    "et les pistes au format `01. Artiste - Titre` sont d'abord normalisées en `01 - Titre` "
    "avant que les singles ne soient déplacés et allégés de leur numéro dans `Singles/`."
)

racine = champ_dossier(
    "Racine de la bibliothèque", "nettoyer_racine", valeur_defaut="M:/musiques/__autres"
)

if not racine:
    st.stop()

base = Path(racine)
if not base.is_dir():
    st.error(f"Dossier introuvable : {base}")
    st.stop()

if st.button("Analyser", type="primary"):
    barre = st.progress(0.0, text="Analyse des noms…")

    def _prog(fait, total):
        barre.progress(fait / total if total else 1.0, text=f"Artiste {fait}/{total}")

    st.session_state["nettoyer_plan"] = previsualiser_nettoyage(base, progress=_prog)
    st.session_state["nettoyer_racine"] = str(base)
    barre.empty()

plan = st.session_state.get("nettoyer_plan")
if plan is not None:
    racine = st.session_state["nettoyer_racine"]

    if not plan:
        st.success("Rien à nettoyer : tous les noms sont déjà conformes.")
    else:
        st.success(
            f"{len(plan.albums)} dossier(s) d'album et {len(plan.pistes)} fichier(s) à renommer."
        )

        if plan.albums:
            st.markdown("#### Dossiers d'album mal nommés")
            st.dataframe(
                pd.DataFrame(
                    [
                        {"Nom actuel": r.ancien.name, "Nom cible": r.nouveau.name}
                        for r in plan.albums
                    ]
                ),
                use_container_width=True,
                hide_index=True,
            )

        if plan.pistes:
            st.markdown("#### Fichiers mal nommés")
            st.dataframe(
                pd.DataFrame(
                    [
                        {
                            "Album": r.ancien.parent.name,
                            "Nom actuel": r.ancien.name,
                            "Nom cible": r.nouveau.name,
                        }
                        for r in plan.pistes
                    ]
                ),
                use_container_width=True,
                hide_index=True,
                height=400,
            )

        st.divider()
        st.warning(
            "L'opération renomme des dossiers et des fichiers. Aucun fichier n'est "
            "supprimé, et un journal d'annulation est créé.",
            icon="⚠️",
        )
        if st.button("Appliquer le nettoyage", type="primary"):
            with st.spinner("Renommage en cours…"):
                resultat = appliquer(plan, racine)
            st.success(
                f"{resultat.nb_renommes} renommage(s) effectué(s). "
                f"Journal : `{resultat.journal.name}`"
            )
            if resultat.erreurs:
                st.warning(
                    f"{len(resultat.erreurs)} élément(s) n'ont pas pu être renommés "
                    "(verrouillé, chemin trop long, permission). Aucun fichier perdu."
                )
                with st.expander("Voir les erreurs"):
                    for e in resultat.erreurs:
                        st.write(f"- {e}")
            st.session_state.pop("nettoyer_plan", None)

if chemin_journal_nettoyage(base).is_file():
    st.divider()
    if st.button("↩️ Annuler le dernier nettoyage"):
        st.success(f"{annuler(base)} action(s) annulée(s).")
