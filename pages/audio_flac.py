from pathlib import Path

import pandas as pd
import streamlit as st

from tools.audio import (
    EXT_AUDIO_NON_FLAC,
    convertir_dossier_flac,
    inventaire_non_flac,
)
from ui import champ_dossier

st.title("💿 Convertir en FLAC")
st.caption(
    "Inventorie les fichiers audio non-FLAC d'un dossier (MP3, M4A, WAV, etc.) "
    "et les convertit en FLAC avec conservation des métadonnées, en remplaçant les originaux."
)

dossier = champ_dossier(
    "Dossier à analyser", "audio_flac_dossier", placeholder="M:/musiques/album"
)

col1, col2 = st.columns(2)
with col1:
    recursif = st.checkbox("Inclure les sous-dossiers", value=True)
with col2:
    remplacer = st.checkbox(
        "Remplacer les originaux (supprimer la source après conversion)",
        value=True,
    )

if not dossier:
    st.stop()

base = Path(dossier)
if not base.is_dir():
    st.error(f"Dossier introuvable : {base}")
    st.stop()

# 1. Inventaire des fichiers non-FLAC
fichiers = inventaire_non_flac(base, recursif=recursif)

st.markdown("#### 📋 Inventaire des fichiers non-FLAC")

if not fichiers:
    st.success("Aucun fichier non-FLAC détecté dans ce dossier.")
    st.stop()

# Statistiques et répartition
taille_totale = sum(f.stat().st_size for f in fichiers)
par_ext: dict[str, int] = {}
for f in fichiers:
    ext = f.suffix.lower()
    par_ext[ext] = par_ext.get(ext, 0) + 1

repartition = ", ".join(
    f"{count} {ext.upper().lstrip('.')}" for ext, count in sorted(par_ext.items())
)

m1, m2, m3 = st.columns(3)
m1.metric("Fichiers à convertir", len(fichiers))
m2.metric("Poids total", f"{taille_totale / (1024 * 1024):.1f} Mo")
m3.metric("Formats détectés", repartition)

# Tableau détaillé
lignes = []
for f in fichiers:
    rel = f.relative_to(base)
    lignes.append(
        {
            "Fichier": f.name,
            "Format": f.suffix.lower().lstrip("."),
            "Dossier": str(rel.parent) if str(rel.parent) != "." else "(racine)",
            "Taille (Ko)": f"{f.stat().st_size / 1024:.0f}",
        }
    )

st.dataframe(pd.DataFrame(lignes), use_container_width=True, hide_index=True)

st.divider()

if remplacer:
    st.warning(
        "⚠️ Les fichiers originaux seront **remplacés** : chaque fichier converti en "
        "FLAC avec succès sera supprimé.",
        icon="⚠️",
    )

if st.button(f"Convertir {len(fichiers)} fichier(s) en FLAC", type="primary"):
    with st.status("Conversion en FLAC en cours…", expanded=True) as status:
        res = convertir_dossier_flac(
            fichiers,
            remplacer=remplacer,
            log=lambda m: st.write(m),
        )
        if res.erreurs:
            status.update(
                label=f"Terminé avec {len(res.erreurs)} erreur(s) ⚠️",
                state="error",
            )
            st.error(
                f"{len(res.convertis)} fichier(s) converti(s), "
                f"{len(res.erreurs)} erreur(s) rencontrée(s)."
            )
            with st.expander("Détail des erreurs"):
                for src, err in res.erreurs:
                    st.write(f"- `{src.name}` : {err}")
        else:
            status.update(
                label=f"Terminé — {len(res.convertis)} fichier(s) converti(s) ✅",
                state="complete",
            )
            st.success(
                f"Tous les fichiers ({len(res.convertis)}) ont été convertis en FLAC avec succès !"
            )
