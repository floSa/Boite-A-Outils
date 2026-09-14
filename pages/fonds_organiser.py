"""Page Streamlit : Organiser les fonds d'écran."""

from pathlib import Path

import streamlit as st

st.title("🖼️ Organiser les fonds d'écran")
st.caption(
    "Trie les fonds d'écran PNG du dossier source vers le dossier trié : "
    "détection des doublons (vers `Doublons/`), appariement paysage ↔ portrait par SIFT, "
    "numérotation continue (`NNN_pa.png` / `NNN_po.png`) et isolation des orphelins (vers `A_verifier/`)."
)

try:
    import cv2  # noqa: F401

    from tools import fonds
except ModuleNotFoundError:
    st.warning(
        "Cet outil nécessite l'extra **vision** (OpenCV) : `uv sync --extra vision`.",
        icon="📦",
    )
    st.stop()

from ui import champ_dossier

DEFAUT_SRC = "C:/Users/FLORIAN/Pictures/FDE"
DEFAUT_TRIES = "C:/Users/FLORIAN/Pictures/FDE/Fonds_Tries"

source = champ_dossier(
    "Dossier source (fonds d'écran à trier — PNG uniquement à la racine)",
    "fonds_organiser_source",
    valeur_defaut=DEFAUT_SRC,
)
dossier_tries = champ_dossier(
    "Dossier de sortie (collection triée)",
    "fonds_organiser_dossier_tries",
    valeur_defaut=DEFAUT_TRIES,
)

col_mode, col_undo = st.columns([2, 1])
mode_transfert = col_mode.radio(
    "Action sur les fichiers source",
    ["Déplacer (retirer de la source)", "Copier (conserver la source)"],
    horizontal=True,
    key="fonds_mode_transfert",
)

with st.expander("⚙️ Paramètres avancés"):
    c1, c2 = st.columns(2)
    seuil_inliers = c1.slider(
        "Seuil d'inliers minimum (appariement)", 10, 100, fonds.SEUIL_INLIERS
    )
    seuil_phash = c2.slider(
        "Tolérance doublon visuel (pHash)",
        0,
        10,
        4,
        help="Différence maximale d'empreinte pour considérer deux images comme identiques.",
    )

base_src = Path(source)
base_dst = Path(dossier_tries)

# Bouton de rollback si une opération précédente est réversible
chemin_undo = base_dst / fonds.FICHIER_UNDO if base_dst.is_dir() else None
if chemin_undo and chemin_undo.is_file():
    if col_undo.button("↩️ Annuler le dernier rangement"):
        with st.spinner("Restauration des fichiers…"):
            n = fonds.annuler_organisation(base_dst)
        st.success(f"{n} fichier(s) restauré(s) à leur emplacement d'origine.")
        st.session_state.pop("fonds_plan", None)
        st.rerun()

st.divider()

if st.button("🔍 Analyser les fonds d'écran", type="primary"):
    if not base_src.is_dir():
        st.error(f"Dossier source introuvable : {base_src}")
        st.stop()
    if base_src.resolve() == base_dst.resolve():
        st.error("Le dossier source et le dossier de sortie doivent être distincts.")
        st.stop()

    with st.status("Analyse en cours…", expanded=True) as status:
        plan = fonds.preparer_organisation(
            base_src,
            base_dst,
            seuil_inliers=seuil_inliers,
            seuil_phash=seuil_phash,
            log=lambda m: st.write(m),
        )
        status.update(label="Analyse terminée ✅", state="complete")

    st.session_state["fonds_plan"] = plan

plan: fonds.PlanOrganisation | None = st.session_state.get("fonds_plan")
if not plan:
    st.stop()

if plan.nb_source_total == 0:
    st.info("Aucun fichier PNG trouvé à la racine du dossier source.")
    st.stop()

# Métriques récapitulatives
m1, m2, m3, m4 = st.columns(4)
m1.metric("PNG analysés", plan.nb_source_total)
m2.metric(
    "Couples formés", len(plan.couples), f"{sum(c.certain for c in plan.couples)} sûrs"
)
m3.metric("Doublons détectés", len(plan.doublons))
m4.metric("Orphelins", len(plan.orphelins))

tab_couples, tab_doublons, tab_orphelins = st.tabs(
    [
        f"🖼️ Couples à classer ({len(plan.couples)})",
        f"👯 Doublons ({len(plan.doublons)})",
        f"❓ À vérifier ({len(plan.orphelins)})",
    ]
)

choisis: list[fonds.Couple] = []

with tab_couples:
    if not plan.couples:
        st.info("Aucun couple paysage ↔ portrait n'a pu être formé.")
    else:
        st.caption(
            "Cochez les couples à numéroter et ranger. Les couples incertains sont décochés par défaut."
        )
        for idx, c in enumerate(plan.couples):
            badge = "✅ Sûr" if c.certain else "⚠️ À vérifier"
            cocher, img_pa, img_po, info = st.columns([1, 3, 2, 3])

            inclus = cocher.checkbox(
                "Ranger",
                value=c.certain,
                key=f"plan_c_{idx}_{c.portrait.name}",
                label_visibility="collapsed",
            )
            if c.paysage.exists():
                img_pa.image(str(c.paysage), use_container_width=True)
            if c.portrait.exists():
                img_po.image(str(c.portrait), use_container_width=True)

            info.write(f"**{badge}**")
            info.write(f"Inliers SIFT : **{c.score}** (2ᵉ : {c.second})")
            info.caption(
                f"Paysage : `{c.paysage.name}`\nPortrait : `{c.portrait.name}`"
            )
            if inclus:
                choisis.append(c)

with tab_doublons:
    if not plan.doublons:
        st.info("Aucun doublon détecté.")
    else:
        st.caption(
            "Ces fichiers existent déjà dans la destination ou en plusieurs exemplaires dans la source. Ils iront dans `Doublons/`."
        )
        for f, motif in plan.doublons:
            st.write(f"• `{f.name}` — *{motif}*")

with tab_orphelins:
    if not plan.orphelins:
        st.info("Aucun orphelin.")
    else:
        st.caption(
            "Ces images n'ont pas trouvé de partenaire ou sont de ratio non standard. Elles iront dans `A_verifier/`."
        )
        for f in plan.orphelins:
            st.write(f"• `{f.name}`")

st.divider()
st.markdown("#### Exécuter le rangement")

deplacer = mode_transfert.startswith("Déplacer")
action_str = "déplacer" if deplacer else "copier"
prochain = fonds.prochain_id(base_dst)

nb_total_orphelins = len(plan.orphelins) + (len(plan.couples) - len(choisis)) * 2

st.write(
    f"Prêt à **{action_str}** : "
    f"**{len(choisis)}** couple(s) (début numérotation : `{prochain:03d}`), "
    f"**{len(plan.doublons)}** doublon(s) → `Doublons/`, "
    f"**{nb_total_orphelins}** image(s) → `A_verifier/`."
)

if st.button("📦 Appliquer le rangement", type="primary"):
    with st.status("Rangement en cours…", expanded=True) as status:
        bilan = fonds.appliquer_organisation(
            plan,
            base_dst,
            deplacer=deplacer,
            couples_selectionnes=choisis,
            log=lambda m: st.write(m),
        )
        status.update(label="Rangement terminé ✅", state="complete")

    if bilan["nb_couples"] > 0:
        st.success(
            f"Rangement terminé avec succès ! "
            f"Couples numérotés de `{bilan['premier_id']}` à `{bilan['dernier_id']}`."
        )
    else:
        st.success("Rangement terminé (aucun couple rangé).")

    st.session_state.pop("fonds_plan", None)
    st.rerun()
