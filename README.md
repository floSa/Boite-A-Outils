# Boîte à outils

**Application Streamlit locale qui regroupe, sous une navigation unique, une collection d'utilitaires personnels pour fichiers, médias et catalogues.**

![Python](https://img.shields.io/badge/Python-3.12-3776AB?logo=python&logoColor=white)
![uv](https://img.shields.io/badge/uv-package_manager-DE5FE9?logo=uv&logoColor=white)
![Streamlit](https://img.shields.io/badge/Streamlit-1.60-FF4B4B?logo=streamlit&logoColor=white)

Chaque outil est un onglet ; la logique métier vit dans le package `tools/`
(fonctions pures, testables), l'interface dans `pages/`.

## Architecture

Principe : **UI fine, logique pure**. Chaque page de `pages/` ne fait qu'appeler une
fonction de `tools/` (testable sans Streamlit) et afficher son résultat.

```mermaid
flowchart TD
  p["pages/ — 1 page par outil"] -->|chemins + options| t["tools/ — logique pure"]
  t --> ff["ffmpeg embarqué (imageio-ffmpeg)"]
  t <--> fs[("Dossiers locaux")]
  t -.-> bm["catalogue BM Lyon"]
  t -->|résultat| p
```

Détails : [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (le COMMENT) et
[docs/CADRAGE.md](docs/CADRAGE.md) (le POURQUOI).

## Démarrage

**Prérequis** : Python `>=3.12` et [`uv`](https://docs.astral.sh/uv/).

```bash
uv sync                              # installe tout (~60 Mo, sans torch)
uv run playwright install chromium  # navigateur pour la vérification BM Lyon
```

Lancer l'application :

```bash
uv run streamlit run app.py
```

## Outils

49 outils, répartis en 9 catégories (calées sur la navigation de `app.py`).

| Catégorie | Outils |
|---|---|
| 🎵 Audio | **Convertir en FLAC** — inventorie les fichiers non-FLAC et les convertit (remplace les originaux)<br>**Normaliser des FLAC** — corrige le gain audio<br>**Convertir un format** — bascule entre formats audio<br>**Extraire l'audio d'une vidéo** — isole la piste audio<br>**Découper** — extrait un segment audio<br>**Normaliser le volume** — égalise le niveau sonore<br>**Renommer depuis les tags** — noms de fichiers ← métadonnées<br>**Éditer les tags en masse** — modifie ID3/Vorbis en lot |
| 🖼️ Images | **Redimensionner / compresser** — réduit taille et poids<br>**Convertir de format** — bascule entre formats (dont HEIC)<br>**Trouver les doublons** — détecte images identiques/similaires<br>**Renuméroter** — renomme en séquence numérotée<br>**Organiser les fonds d'écran** — déduplique (vers `Doublons/`), apparie paysage ↔ portrait et numérote en continu<br>**Filigrane** — incruste un marquage texte |
| 🎬 Vidéo | **Télécharger depuis le web** — récupère des vidéos en ligne (YouTube, Facebook, Dailymotion, Instagram...)<br>**Fusionner** — assemble plusieurs vidéos<br>**Découper** — extrait un segment vidéo<br>**Compresser** — réduit le poids vidéo<br>**Convertir** — bascule entre formats vidéo<br>**Extraire des images** — capture des images fixes<br>**Créer un GIF** — convertit un extrait en GIF |
| 📄 PDF | **Extraire des pages** — isole certaines pages<br>**Fusionner** — assemble plusieurs PDF<br>**Supprimer / pivoter des pages** — édite la structure du PDF<br>**Images ↔ PDF** — convertit dans les deux sens<br>**Compresser** — réduit le poids du PDF<br>**Protéger / déprotéger** — gère le mot de passe<br>**Extraire le texte** — récupère le texte du PDF<br>**Filigrane** — incruste un marquage texte |
| 📁 Fichiers | **Nettoyer les noms** — retire les caractères parasites<br>**Renommer en masse** — motif de renommage global<br>**Renommer depuis un CSV** — table ancien/nouveau nom<br>**Fichiers en double** — détecte les doublons par contenu<br>**Ranger automatiquement** — trie dans des sous-dossiers<br>**Statistiques** — compte et pèse un dossier<br>**Comparer deux dossiers** — diff de contenu<br>**Arborescence → Excel** — exporte la structure des dossiers<br>**HTML → Markdown** — convertit des captures web (SingleFile) |
| 🔤 Données | **Convertir un tableau** — CSV ↔ Excel ↔ JSON<br>**Nettoyer des lignes** — filtre et déduplique des lignes |
| 🗣️ Voix & langues | **Lire un texte à voix haute** — synthèse vocale locale (Kokoro)<br>**Traduire un texte** — hors-ligne, ~200 langues (NLLB-200)<br>**Transcrire un audio / une vidéo** — texte + sous-titres (Whisper) |
| 🎼 Bibliothèque perso | **Catalogue de la bibliothèque** — scanne un NAS en CSV/Excel<br>**Uniformiser les noms** — nettoie les noms dossiers/fichiers<br>**Regrouper les singles** — isole les albums à un seul titre |
| 📚 Bibliothèque municipale | **Trier des cotes** — épuration des statuts parasites ((En rayon), dates de prêt) et classement par cote (Dewey ou archive)<br>**Vérifier la disponibilité BM Lyon** — statut actuel au catalogue<br>**Récolter les CD d'artistes** — liste tous les CD trouvés |

> Les outils audio/vidéo utilisent le **ffmpeg embarqué** par `imageio-ffmpeg` (aucune
> installation système requise).
>
> La vérification BM Lyon nécessite en plus le navigateur Playwright :
> `uv run playwright install chromium`.
>
> Le **filigrane** (texte répété en mosaïque : angle, espacement, couleur, taille,
> opacité) est **incrusté en image**, y compris dans les PDF. Le texte n'y est donc
> pas sélectionnable, et il reste retirable par un éditeur PDF : c'est un
> **marquage, pas une protection**. L'original n'est jamais écrasé — la sortie est
> suffixée `_filigrane`.
>
> La **synthèse vocale** (Kokoro) tourne en local sur CPU via `onnxruntime`
> (aucun PyTorch, espeak-ng embarqué). Le modèle (~340 Mo) se télécharge **au
> premier usage** depuis la page, puis est mis en cache. Accélération GPU NVIDIA
> facultative : `uv sync --extra gpu`.
>
> La **traduction** (NLLB-200) tourne en local via `ctranslate2` (aucun PyTorch ;
> `transformers` sert seulement de tokenizer). Le modèle (~600 Mo, 200 langues) se
> télécharge **au premier usage**, puis est mis en cache. Modèle NLLB sous licence
> **CC-BY-NC** (usage non commercial).
>
> La **transcription** (Whisper via `faster-whisper`) tourne en local sur
> CTranslate2 (aucun PyTorch ; `av` décode audio et vidéo). Le modèle choisi
> (jusqu'à ~1,6 Go pour `large-v3-turbo`) se télécharge **au premier usage**,
> puis est mis en cache. Modèle et moteur sous licence **MIT**.

## Tests

```bash
uv run pytest
```

Un fichier de test par module de `tools/` (logique pure ; le matching BM Lyon est testé
sans navigateur), plus `tests/test_pages.py` qui vérifie que **chaque page se rend sans
exception** (smoke-test via `streamlit.testing.v1.AppTest`).

## Structure du projet

```text
outils_maison/
├── app.py              # entrée Streamlit (navigation multipage)
├── tools/              # logique pure, sans Streamlit (testable)
│   ├── ffmpeg_utils.py #   accès au binaire ffmpeg embarqué
│   ├── audio.py        #   normalisation FLAC, extraction, renommage par tags
│   ├── musique.py      #   regroupement de singles
│   ├── images.py       #   redimensionner, convertir, dédupliquer, renuméroter
│   ├── fonds.py        #   organisation des fonds d'écran (SIFT, RANSAC, doublons, numérotation)
│   ├── video.py        #   fusionner, découper, compresser
│   ├── video_dl.py     #   téléchargement de vidéos web (YouTube, Facebook, etc. via yt-dlp)
│   ├── pdf.py          #   extraire, fusionner, pages, images ↔ PDF
│   ├── watermark.py    #   filigrane texte en mosaïque (images + PDF)
│   ├── files.py        #   noms de fichiers, doublons, arborescence (+ annulation)
│   ├── data.py         #   conversions CSV / Excel / JSON
│   ├── tts.py          #   synthèse vocale locale (Kokoro / onnxruntime)
│   ├── traduction.py   #   traduction hors-ligne (NLLB-200 / CTranslate2)
│   ├── transcription.py #  transcription audio/vidéo (Whisper / faster-whisper)
│   ├── biblio.py       #   tri de cotes de bibliothèque
│   └── bm_lyon.py      #   disponibilité au catalogue BM Lyon (scraping)
├── pages/              # une page Streamlit par outil
├── tests/              # tests pytest (logique + rendu des pages)
├── notebooks_archive/  # notebooks d'origine, conservés en référence
└── docs/               # cadrage et architecture
```

## Documentation

- [docs/CADRAGE.md](docs/CADRAGE.md) — objectifs, périmètre, hypothèses, décisions (le POURQUOI).
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — modules, flux, stack, sécurité, limites (le COMMENT).

## Licences & composants

Licences usuelles des briques utilisées — **à vérifier selon la version installée**
(certaines évoluent). En cas de doute : *à confirmer*.

| Composant | Rôle | Licence (usuelle) |
|---|---|---|
| Streamlit | Interface web | Apache-2.0 |
| pandas | Données / tableaux | BSD-3-Clause |
| openpyxl | Lecture/écriture Excel | MIT |
| pypdf | Manipulation PDF | BSD-3-Clause |
| PyMuPDF | Rendu / extraction PDF | AGPL-3.0 (ou licence commerciale) |
| moviepy | Traitement vidéo | MIT |
| yt-dlp | Téléchargement vidéo web | Unlicense |
| imageio-ffmpeg | Binaire ffmpeg embarqué (transitif) | BSD-2-Clause (ffmpeg : LGPL/GPL) |
| mutagen | Tags audio | GPL-2.0-or-later |
| Pillow | Images | MIT-CMU (HPND) |
| pillow-heif | Support HEIC | *à confirmer* (BSD/Apache selon version) |
| ImageHash | Empreintes perceptuelles | BSD-2-Clause |
| tqdm | Barres de progression | MPL-2.0 / MIT |
| opencv-python | Vision (SIFT/RANSAC) | Apache-2.0 |
| Playwright | Navigateur pour scraping | Apache-2.0 |
| kokoro-onnx | Synthèse vocale (moteur ONNX) | MIT |
| Kokoro-82M | Modèle de voix (téléchargé) | Apache-2.0 |
| onnxruntime | Exécution du modèle (CPU/GPU) | MIT |
| espeakng-loader / phonemizer-fork | Phonémisation (espeak-ng embarqué) | GPL-3.0 (espeak-ng) |
| ctranslate2 | Traduction (moteur d'inférence) | MIT |
| transformers | Tokenizer de traduction | Apache-2.0 |
| sentencepiece | Tokenisation sous-mots | Apache-2.0 |
| NLLB-200 (distillé 600M) | Modèle de traduction (téléchargé) | **CC-BY-NC-4.0** (non commercial) |
| faster-whisper | Transcription (runtime CTranslate2) | MIT |
| av (PyAV) | Décodage audio/vidéo (ffmpeg) | BSD-3-Clause |
| Whisper (modèles) | Modèle de transcription (téléchargé) | MIT |
| **Ce projet** | Code applicatif | MIT — Copyright (c) 2026 floSa |
