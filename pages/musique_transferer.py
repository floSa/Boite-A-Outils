from pathlib import Path

import pandas as pd
import streamlit as st

from tools.musique_transferer import (
    executer_transfert_robocopy,
    preparer_transfert,
)
from ui import champ_dossier

st.title("🚚 Transférer vers la bibliothèque")
st.caption(
    "Transfère un ou plusieurs dossiers sources structurés en `Artiste / Album` vers une "
    "bibliothèque unique via **Robocopy** (Ctrl+C Ctrl+V rapide avec horodatages), puis supprime "
    "les dossiers sources une fois le transfert validé. Un journal de retour en arrière est téléchargeable."
)

st.markdown("#### 1. Bibliothèque de destination")
destination = champ_dossier(
    "Dossier final de destination",
    "musique_transferer_dest",
    valeur_defaut="M:/musiques/__autres",
)

st.divider()
st.markdown("#### 2. Dossiers sources à transférer")

# Gestion dynamique de la liste des dossiers sources
if "transfert_sources_liste" not in st.session_state:
    st.session_state["transfert_sources_liste"] = []

# Saisie par zone multi-lignes ou ajout unitaire
onglet_multi, onglet_unitaire = st.tabs(["Coller plusieurs chemins", "Ajouter un dossier"])

with onglet_multi:
    texte_chemins = st.text_area(
        "Chemins des dossiers sources (un chemin par ligne)",
        placeholder="C:/Users/.../Dossier1\nC:/Users/.../Dossier2",
        help="Colle ici un ou plusieurs chemins complets vers des dossiers construits en Artiste / Album.",
    )
    if st.button("Charger les chemins collés"):
        lignes = [
            ligne.strip().strip('"').strip("'")
            for ligne in texte_chemins.splitlines()
            if ligne.strip()
        ]
        for l in lignes:
            if l not in st.session_state["transfert_sources_liste"]:
                st.session_state["transfert_sources_liste"].append(l)
        st.rerun()

with onglet_unitaire:
    nouveau_dossier = champ_dossier(
        "Sélectionner un dossier source",
        "transfert_nouveau_dossier",
        placeholder="C:/Users/.../MonDossier",
    )
    if st.button("➕ Ajouter ce dossier"):
        if nouveau_dossier and nouveau_dossier not in st.session_state["transfert_sources_liste"]:
            st.session_state["transfert_sources_liste"].append(nouveau_dossier)
            st.rerun()

# Affichage des dossiers actuellement sélectionnés
sources_actuelles = st.session_state["transfert_sources_liste"]

if not sources_actuelles:
    st.info("Aucun dossier source sélectionné pour le moment.")
    st.stop()

st.markdown(f"**{len(sources_actuelles)} dossier(s) source(s) sélectionné(s) :**")
a_supprimer = None
for i, src in enumerate(sources_actuelles):
    c1, c2 = st.columns([5, 1])
    c1.code(src, language="text")
    if c2.button("Retirer", key=f"del_src_{i}"):
        a_supprimer = i

if a_supprimer is not None:
    st.session_state["transfert_sources_liste"].pop(a_supprimer)
    st.session_state.pop("transfert_plan", None)
    st.rerun()

if st.button("Vider toute la liste"):
    st.session_state["transfert_sources_liste"] = []
    st.session_state.pop("transfert_plan", None)
    st.rerun()

st.divider()
st.markdown("#### 3. Contrôle de conformité et Prévisualisation")

if not destination:
    st.warning("Veuillez renseigner un dossier de destination.")
    st.stop()

dest_path = Path(destination)
if not dest_path.is_dir():
    st.error(f"Le dossier de destination n'existe pas : {destination}")
    st.stop()

if st.button("Contrôler les arborescences et analyser", type="primary"):
    with st.spinner("Contrôle de la structure Artiste / Album de chaque source…"):
        plan = preparer_transfert(sources_actuelles, dest_path)
        st.session_state["transfert_plan"] = plan

plan = st.session_state.get("transfert_plan")
if not plan:
    st.stop()

# Affichage du bilan de chaque dossier source
lignes_statuts = []
tous_valides = True

for s in plan.sources:
    if s.est_valide:
        statut_str = "✅ Conforme (Artiste / Album)"
        taille_mo = s.taille_totale / (1024 * 1024)
        taille_str = f"{taille_mo:.1f} Mo" if taille_mo < 1024 else f"{taille_mo/1024:.2f} Go"
        lignes_statuts.append(
            {
                "Dossier source": str(s.chemin),
                "Statut": statut_str,
                "Artistes": s.nb_artistes,
                "Albums": s.nb_albums,
                "Fichiers": s.nb_fichiers,
                "Taille": taille_str,
            }
        )
    else:
        tous_valides = False
        lignes_statuts.append(
            {
                "Dossier source": str(s.chemin),
                "Statut": "❌ Non conforme",
                "Artistes": s.nb_artistes,
                "Albums": s.nb_albums,
                "Fichiers": s.nb_fichiers,
                "Taille": "—",
            }
        )

st.dataframe(pd.DataFrame(lignes_statuts), use_container_width=True, hide_index=True)

# Affichage des anomalies éventuelles
sources_invalides = [s for s in plan.sources if not s.est_valide]
if sources_invalides:
    st.error(
        "⚠️ Certains dossiers ne respectent pas l'arborescence requise `Artiste / Album`. "
        "Le transfert est bloqué tant que ces dossiers ne sont pas corrigés ou retirés :"
    )
    for s in sources_invalides:
        with st.expander(f"Détails des anomalies pour : {s.chemin}"):
            for anom in s.anomalies:
                st.write(f"- {anom}")
    st.stop()

# Si tout est conforme
st.success(
    f"Tous les dossiers sont conformes ! **{len(plan.tous_fichiers)}** fichier(s) prêts à être transférés "
    f"vers `{dest_path.name}`."
)

if plan.collisions:
    st.warning(
        f"ℹ️ **{len(plan.collisions)}** fichier(s) existent déjà dans la destination. "
        "Robocopy les mettra à jour si les sources sont plus récentes ou de taille différente.",
        icon="⚠️",
    )

st.divider()
st.markdown("#### 4. Exécution du transfert Robocopy")

st.warning(
    "⚠️ **Action irréversible sur les dossiers sources :** Robocopy va copier l'ensemble des fichiers "
    "dans la destination, puis **les dossiers sources seront supprimés**. "
    "Vous pourrez télécharger un fichier journal de restauration juste après.",
    icon="⚠️",
)

if st.button("🚀 Lancer le transfert Robocopy et supprimer les sources", type="primary"):
    with st.status("Transfert Robocopy en cours…", expanded=True) as status:
        res = executer_transfert_robocopy(plan, log=lambda m: st.write(m))
        if res.succes:
            status.update(label="Transfert Robocopy terminé avec succès ✅", state="complete")
        else:
            status.update(label="Transfert terminé avec des alertes ⚠️", state="error")

    if res.succes:
        st.success(
            f"🎉 Transfert terminé : **{res.nb_fichiers_copies}** fichier(s) copiés. "
            f"Les **{len(res.sources_traitees)}** dossier(s) sources ont été supprimés."
        )
    else:
        st.error(f"Erreurs rencontrées lors du transfert : {res.erreurs}")

    # Section de téléchargement du journal (sans écriture sur le disque)
    st.divider()
    st.markdown("### 📥 Télécharger le journal de retour en arrière")
    st.caption(
        "Ce journal n'a pas été écrit dans vos dossiers musicaux. Téléchargez-le maintenant "
        "pour conserver l'historique complet des fichiers transférés et de leurs emplacements d'origine."
    )

    c_dl1, c_dl2 = st.columns(2)
    with c_dl1:
        st.download_button(
            "📥 Télécharger le journal (.json)",
            data=res.journal_json,
            file_name="journal_transfert_robocopy.json",
            mime="application/json",
            help="Contient les correspondances précises source_origine -> destination_actuelle.",
        )
    with c_dl2:
        st.download_button(
            "📥 Télécharger le compte-rendu (.txt)",
            data=res.journal_texte,
            file_name="rapport_transfert_robocopy.txt",
            mime="text/plain",
        )

    # Réinitialiser la liste des sources après succès
    if res.succes:
        st.session_state["transfert_sources_liste"] = []
        st.session_state.pop("transfert_plan", None)
