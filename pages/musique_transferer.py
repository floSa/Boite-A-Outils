from pathlib import Path

import streamlit as st

from tools.musique_transferer import (
    executer_transfert_robocopy,
    preparer_transfert,
)
from ui import champ_dossier

st.title("🚚 Transférer vers la bibliothèque")
st.caption(
    "Transfère un ou plusieurs dossiers sources structurés en `Artiste / Album` vers une "
    "bibliothèque unique via **Robocopy**, puis supprime les dossiers sources une fois le "
    "transfert validé. Un journal de retour en arrière est téléchargeable à la fin."
)

# Initialisation de la liste des dossiers sources
if "transfert_sources_liste" not in st.session_state:
    st.session_state["transfert_sources_liste"] = []

# =============================================================================
# 1. Dossiers sources à transférer (EN PREMIER)
# =============================================================================
st.markdown("### 1. Dossiers sources à transférer")
st.caption(
    "Cliquez sur **📂 Parcourir** pour sélectionner un dossier sur votre machine, "
    "puis validez son ajout dans le tableau récapitulatif."
)

col_parc, col_aj = st.columns([3, 1], vertical_alignment="bottom")

with col_parc:
    dossier_choisi = champ_dossier(
        "Sélectionner un dossier",
        "transfert_nouveau_dossier",
    )

with col_aj:
    if st.button("➕ Ajouter ce dossier", use_container_width=True, type="primary"):
        if dossier_choisi and dossier_choisi.strip():
            chemin_net = dossier_choisi.strip()
            if chemin_net not in st.session_state["transfert_sources_liste"]:
                st.session_state["transfert_sources_liste"].append(chemin_net)
                st.session_state["transfert_nouveau_dossier"] = ""
                st.session_state.pop("transfert_plan", None)
                st.rerun()
            else:
                st.warning("Ce dossier est déjà présent dans la liste.")
        else:
            st.warning("Veuillez d'abord sélectionner un dossier avec « Parcourir ».")

# Tableau récapitulatif HTML des dossiers sélectionnés
sources_actuelles = st.session_state["transfert_sources_liste"]

if sources_actuelles:
    lignes_html = []
    for idx, dossier in enumerate(sources_actuelles, start=1):
        p = Path(dossier)
        existe = p.is_dir()
        badge_statut = (
            '<span style="background: rgba(46, 125, 50, 0.2); color: #4caf50; padding: 3px 8px; border-radius: 10px; font-weight: 600; font-size: 0.85em;">✔ Présent</span>'
            if existe
            else '<span style="background: rgba(211, 47, 47, 0.2); color: #ef5350; padding: 3px 8px; border-radius: 10px; font-weight: 600; font-size: 0.85em;">✖ Introuvable</span>'
        )
        lignes_html.append(
            f'<tr style="border-bottom: 1px solid rgba(128, 128, 128, 0.2);">'
            f'<td style="padding: 10px 12px; font-weight: bold; width: 50px; text-align: center;">{idx}</td>'
            f'<td style="padding: 10px 12px; font-family: monospace; font-size: 0.95em; word-break: break-all;">{dossier}</td>'
            f'<td style="padding: 10px 12px; text-align: center; width: 130px;">{badge_statut}</td>'
            f'</tr>'
        )

    corps_lignes = "".join(lignes_html)
    tableau_html = (
        '<div style="margin: 15px 0 20px 0; border: 1px solid rgba(128, 128, 128, 0.3); border-radius: 8px; overflow: hidden;">'
        '<table style="width: 100%; border-collapse: collapse; text-align: left;">'
        '<thead>'
        '<tr style="background-color: rgba(128, 128, 128, 0.15); border-bottom: 2px solid rgba(128, 128, 128, 0.3);">'
        '<th style="padding: 10px 12px; width: 50px; text-align: center;">#</th>'
        '<th style="padding: 10px 12px;">Dossier source</th>'
        '<th style="padding: 10px 12px; width: 130px; text-align: center;">État</th>'
        '</tr>'
        '</thead>'
        f'<tbody>{corps_lignes}</tbody>'
        '</table>'
        '</div>'
    )
    st.html(tableau_html)

    col_retrait, col_vider = st.columns([3, 1], vertical_alignment="center")
    with col_retrait:
        dossier_a_retirer = st.selectbox(
            "Retirer un dossier",
            options=["— Retirer un dossier de la liste —"] + sources_actuelles,
            index=0,
            label_visibility="collapsed",
        )
        if dossier_a_retirer != "— Retirer un dossier de la liste —":
            if st.button("🗑️ Retirer de la liste"):
                st.session_state["transfert_sources_liste"].remove(dossier_a_retirer)
                st.session_state.pop("transfert_plan", None)
                st.rerun()
    with col_vider:
        if st.button("🗑️ Tout vider", use_container_width=True):
            st.session_state["transfert_sources_liste"] = []
            st.session_state.pop("transfert_plan", None)
            st.rerun()
else:
    st.info("Aucun dossier dans la liste. Cliquez sur **📂 Parcourir** ci-dessus, puis sur **➕ Ajouter ce dossier**.")

st.divider()

# =============================================================================
# 2. Dossier de destination (EN DEUXIÈME)
# =============================================================================
st.markdown("### 2. Dossier de destination")
destination = champ_dossier(
    "Dossier final de destination (bibliothèque principale)",
    "musique_transferer_dest",
    valeur_defaut="M:/musiques/__autres",
)

st.divider()

# =============================================================================
# 3. Contrôle de conformité et Prévisualisation
# =============================================================================
st.markdown("### 3. Contrôle de conformité et Prévisualisation")

if not sources_actuelles:
    st.info("Ajoutez au moins un dossier source à l'étape 1 pour lancer le contrôle.")
    st.stop()

if not destination:
    st.warning("Veuillez renseigner le dossier de destination à l'étape 2.")
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

st.dataframe(lignes_statuts, use_container_width=True)

# Affichage des anomalies si des dossiers sont non conformes
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

# =============================================================================
# 4. Exécution du transfert Robocopy
# =============================================================================
st.markdown("### 4. Exécution du transfert Robocopy")

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
