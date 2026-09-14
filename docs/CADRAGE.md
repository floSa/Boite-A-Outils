# Cadrage — Boîte à outils

Le **POURQUOI** (cahier des charges). Le **COMMENT** est dans
[ARCHITECTURE.md](ARCHITECTURE.md). Sections numérotées, séparées par `---`.

## 1. Pitch

Une application Streamlit locale qui regroupe, sous une navigation unique, une
collection d'utilitaires personnels pour manipuler fichiers, médias et catalogues.

1. **Traiter des médias en lot** (audio, images, vidéo, PDF) sans ligne de commande.
2. **Ranger et assainir des dossiers** (noms de fichiers, doublons, rangement,
   statistiques, comparaison, arborescence → Excel), avec prévisualisation et annulation.
3. **Gérer trois cas « catalogue » spécifiques** : tri et épuration stricte de cotes de
   bibliothèque (suppression des mentions `(En rayon)`, statuts et dates), vérification de
   disponibilité et récolte de CD par artiste au catalogue de la BM de Lyon.
4. **Lire un texte à voix haute** en local (synthèse vocale open-source, voix et
   vitesse réglables), sans service tiers ni PyTorch.
5. **Traduire un texte** hors-ligne (anglais → français et ~200 langues), sans
   service tiers ni PyTorch.
6. **Transcrire un audio/une vidéo** en texte et sous-titres, en local, sans
   service tiers ni PyTorch.
7. **Marquer un document** (image ou PDF) d'un filigrane texte répété — angle,
   espacement, couleur, taille et opacité réglables.

---

## 2. Objectifs & périmètre

**Dans le périmètre** :
- Regrouper des scripts jetables (les notebooks de `notebooks_archive/`) en une seule
  app à onglets, réutilisable et testée.
- Fonctionner en **local**, sans installation système lourde (ffmpeg embarqué).
- Garder la logique métier **pure et testable**, indépendante de l'UI.

**Hors périmètre** :
- Toute mise en ligne / multi-utilisateur / authentification (usage personnel, poste unique).
- Persistance en base de données : l'app opère directement sur des dossiers locaux.
- Traitement de médias « cloud » ou API tierces (hors scraping BM Lyon, ponctuel).

---

## 3. Contraintes (fermes)

| Contrainte | Détail |
|---|---|
| Exécution | Local, poste unique (chemins Windows saisis en clair, ex. `M:/musiques`) |
| Runtime | Python `>=3.12`, projet géré avec `uv` |
| Installation | Pas de binaire système requis pour l'audio/vidéo (ffmpeg embarqué) |
| Poids | Les dépendances lourdes (OpenCV, Playwright) sont des **extras** optionnels |

---

## 4. Hypothèses

- **Usage mono-utilisateur, données de confiance** : les chemins sont saisis par le
  propriétaire de la machine ; pas de contrôle d'accès ni de validation d'entrée forte.
- **Windows comme environnement principal** : exemples de chemins et gestion des chemins
  Unicode (`np.fromfile` dans `fonds.py`) orientés Windows — reste portable pour le reste.
- **Catalogue BM Lyon stable à court terme** : le scraping suppose une structure de page
  donnée ; il est marqué best-effort et peut casser à tout changement du site.

---

## 5. Stack technique

Voir le tableau détaillé en [ARCHITECTURE.md §3](ARCHITECTURE.md#3-stack-technologique)
et le tableau des licences dans le [README](../README.md#licences--composants).

| Brique | Choix | Licence usuelle (à vérifier par version) |
|---|---|---|
| Interface | Streamlit | Apache-2.0 |
| Données / tableurs | pandas · openpyxl | BSD-3-Clause · MIT |
| PDF | pypdf · PyMuPDF | BSD-3-Clause · AGPL-3.0 |
| Images | Pillow · pillow-heif · ImageHash | MIT-CMU (HPND) · *à confirmer* · BSD-2-Clause |
| Médias | moviepy · ffmpeg embarqué | MIT · LGPL/GPL (binaire) |
| Vision | opencv-python | Apache-2.0 |
| Scraping | Playwright | Apache-2.0 |
| Synthèse vocale | kokoro-onnx · onnxruntime (modèle Kokoro-82M) | MIT · MIT (modèle Apache-2.0) |
| Traduction | ctranslate2 · transformers (modèle NLLB-200) | MIT · Apache-2.0 (modèle **CC-BY-NC**) |
| Ce projet | Code applicatif | MIT — Copyright (c) 2026 floSa |

---

## 6. Décisions

**Décisions figées**
- Séparer la logique (`tools/`) de l'UI (`pages/`) : logique testable sans Streamlit.
- ffmpeg embarqué (`imageio-ffmpeg`) plutôt que ffmpeg système.
- Vision (`opencv-python`) et scraping (`playwright`) en dépendances de base : un
  seul `uv sync` installe tout (le navigateur Playwright se télécharge à part).
- Prévisualiser puis appliquer, avec journal d'annulation, pour toute opération
  destructive sur les fichiers.
- Synthèse vocale par **Kokoro** (onnxruntime, sans PyTorch, espeak-ng embarqué)
  plutôt que par un moteur à PyTorch/GPU : reste local et léger. Justification
  contrastive en [ARCHITECTURE.md §6](ARCHITECTURE.md#6-décisions-darchitecture).
- Filigrane **rasterisé** (mosaïque Pillow incrustée) plutôt que texte vectoriel PDF :
  un seul moteur de rendu pour les images et les PDF. Conséquence assumée — le
  filigrane est un **marquage, pas une protection** (texte non sélectionnable,
  retirable par un éditeur PDF). Justification contrastive en
  [ARCHITECTURE.md §6](ARCHITECTURE.md#6-décisions-darchitecture).

(Justifications contrastives détaillées en
[ARCHITECTURE.md §6](ARCHITECTURE.md#6-décisions-darchitecture).)

**À trancher**
- Fixer `imageio-ffmpeg` en dépendance directe (aujourd'hui transitif). `<à confirmer>`
- Étendre le filigrane au **traitement par dossier** et à une **plage de pages** PDF
  (aujourd'hui : un fichier à la fois, toutes les pages). `<à confirmer>`
- Filigrane **image/logo** en plus du texte seul. `<à confirmer>`

---

## 7. Stratégie de tests

- **Logique** : un fichier de test par module métier (`tests/test_audio.py`,
  `test_images.py`, `test_pdf.py`, `test_watermark.py`, `test_files.py`, `test_data.py`,
  `test_fonds.py`, `test_biblio.py`, `test_musique.py`, `test_catalogue.py`,
  `test_clean_library.py`, `test_html_md.py`, `test_bm_lyon.py`, `test_tts.py`,
  `test_traduction.py`, `test_transcription.py`). Les modules à ressource externe sont
  testés **sans cette ressource** : le matching BM Lyon **sans navigateur** (fonctions
  pures isolées de Playwright), la synthèse vocale, la traduction et la transcription
  **sans télécharger leur modèle** (découpage, encodage, garde-fous). Le filigrane est
  vérifié sur une image et un PDF **factices générés à la volée** (dimensions
  préservées, pixels effectivement modifiés, nombre de pages conservé).
- **Rendu** : `tests/test_pages.py` charge chaque page via `streamlit.testing.v1.AppTest`
  et vérifie qu'elle se rend sans exception à entrées vides (smoke-test).
- Lancement : `uv run pytest`.

---

## 8. Références

- Notebooks d'origine conservés dans [`notebooks_archive/`](../notebooks_archive/) :
  matière première dont l'app est la consolidation.
- Logique de scraping BM Lyon reprise d'un projet antérieur « Musique_Tools »
  (éprouvée sur ~900 albums), cf. docstring de [`bm_lyon.py`](../tools/bm_lyon.py).
