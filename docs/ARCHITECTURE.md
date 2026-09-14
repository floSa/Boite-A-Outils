# Architecture — Boîte à outils

Doc technique (le **COMMENT**). Le **POURQUOI** est dans [CADRAGE.md](CADRAGE.md).
Sections numérotées, séparées par `---`.

## 1. Vue d'ensemble

Application **Streamlit multipage** locale. Un principe structurant : **séparation
stricte UI / logique**.

- La **logique métier** vit dans le package [`tools/`](../tools/) : fonctions pures,
  sans aucun `import streamlit`, donc testables en isolation.
- L'**interface** vit dans [`pages/`](../pages/) : une page Streamlit par outil, qui ne
  fait que collecter des chemins/options, appeler `tools/`, puis afficher le résultat.
- Le **point d'entrée** [`app.py`](../app.py) déclare la navigation via `st.navigation`
  / `st.Page` (9 rubriques + Accueil).

Tout traite des **dossiers/fichiers locaux** (chemins saisis en clair, ex. `M:/musiques`).
Aucune donnée ne sort de la machine, sauf l'outil « BM Lyon » qui interroge un site public.
Les outils de **synthèse vocale**, de **traduction** et de **transcription** téléchargent
chacun leur modèle une seule fois (GitHub / HuggingFace), puis fonctionnent hors-ligne.

---

## 2. Modules de logique (`tools/`)

| Module | Rôle | Dépendances clés |
|---|---|---|
| [`ffmpeg_utils.py`](../tools/ffmpeg_utils.py) | Accès au binaire **ffmpeg embarqué** (`imageio-ffmpeg`), lancement de commandes, durée média | `imageio-ffmpeg`, `subprocess` |
| [`audio.py`](../tools/audio.py) | Normalisation FLAC, conversion, extraction, découpe, volume, tags | `mutagen`, ffmpeg |
| [`musique.py`](../tools/musique.py) | Regroupement de singles | `<à confirmer>` |
| [`catalogue.py`](../tools/catalogue.py) | Catalogue CSV/Excel d'une bibliothèque musicale (NAS), 2 ou 3 niveaux selon le dossier de catégorie | `pandas`, `pathlib` |
| [`clean_library.py`](../tools/clean_library.py) | Normalisation des noms `Artiste\Album\Titres` (noms de fichiers seuls, jamais les tags), prévisualisation + annulation | `tools.files`, `re`, `unicodedata` |
| [`images.py`](../tools/images.py) | Redimensionner, convertir (dont HEIC), dédupliquer, renuméroter | `pillow`, `pillow-heif`, `imagehash` |
| [`fonds.py`](../tools/fonds.py) | Organisation des fonds d'écran : déduplication (SHA-256 + pHash), appariement paysage↔portrait (SIFT + RANSAC), numérotation continue, rollback | `opencv-python`, `imagehash`, `pillow` |
| [`video.py`](../tools/video.py) | Fusionner, découper, compresser, convertir, extraire images, GIF | `moviepy`, ffmpeg |
| [`pdf.py`](../tools/pdf.py) | Extraire/fusionner/pivoter des pages, images↔PDF, compresser, protéger, texte | `pypdf`, `pymupdf` |
| [`watermark.py`](../tools/watermark.py) | Filigrane texte en mosaïque (angle, espacement, couleur, opacité) sur images et PDF | `pillow`, `pymupdf` |
| [`files.py`](../tools/files.py) | Noms (slugify), doublons (SHA-1), arborescence→Excel, rangement, stats, comparaison, renommage CSV | `pandas`, `openpyxl` |
| [`data.py`](../tools/data.py) | Conversions CSV / Excel / JSON, nettoyage de lignes | `pandas`, `openpyxl` |
| [`html_md.py`](../tools/html_md.py) | Captures HTML (SingleFile) → Markdown, fichier ou dossier récursif, images en `_assets/` ; moteur `html_to_md` copié dans le sous-paquet | `beautifulsoup4`, `lxml`, `readability-lxml`, `markdownify` |
| [`biblio.py`](../tools/biblio.py) | Épuration stricte des statuts parasites et tri naturel de cotes de bibliothèque (Dewey, archives, alphabétique) | `stdlib` (`csv`, `io`, `re`, `dataclasses`, `pathlib`) |
| [`bm_lyon.py`](../tools/bm_lyon.py) | Vérification de disponibilité et récolte de CD par artiste au catalogue BM Lyon (scraping) | `playwright`, `difflib` |
| [`tts.py`](../tools/tts.py) | Synthèse vocale locale (voix, vitesse, CPU/GPU), téléchargement du modèle | `kokoro-onnx`, `onnxruntime`, `numpy` |
| [`traduction.py`](../tools/traduction.py) | Traduction hors-ligne (200 langues, CPU/GPU), téléchargement du modèle | `ctranslate2`, `transformers` (tokenizer), `sentencepiece` |
| [`transcription.py`](../tools/transcription.py) | Transcription audio/vidéo → texte + sous-titres (CPU/GPU), téléchargement du modèle | `faster-whisper` (CTranslate2), `av` |

> Les 48 pages de [`pages/`](../pages/) sont de fines enveloppes UI au-dessus de ces
> modules (une page = un outil, cf. la navigation dans [`app.py`](../app.py)).

---

## 3. Stack technologique

| Couche | Technologie | Version (contrainte `pyproject.toml`) |
|---|---|---|
| Interface web | Streamlit | `>=1.40` |
| Tableurs / données | pandas · openpyxl | `>=2.2` · `>=3.1` |
| PDF | pypdf · PyMuPDF | `>=5.0` · `>=1.28.0` |
| Vidéo / audio | moviepy · ffmpeg (via imageio-ffmpeg) | `>=2.0` · embarqué |
| Tags audio | mutagen | `>=1.47` |
| Images | Pillow · pillow-heif · ImageHash | `>=11.0` · `>=1.4.0` · `>=4.3.2` |
| Progression | tqdm | `>=4.67` |
| Vision | opencv-python | `>=4.10` |
| Scraping | Playwright | `>=1.40` |
| Synthèse vocale | kokoro-onnx · onnxruntime (modèle Kokoro-82M) | `>=0.4` · CPU (extra `gpu`) |
| Traduction | ctranslate2 · transformers (tokenizer) · sentencepiece (modèle NLLB-200 600M) | `>=4.0` · `>=4.40` · `>=0.2` |
| Transcription | faster-whisper (CTranslate2) · av (modèles Whisper) | `>=1.1` |
| Runtime | Python | `>=3.12` |
| Gestion projet | uv | `uv.lock` présent |

`imageio-ffmpeg` (fournisseur du binaire ffmpeg) n'est pas déclaré explicitement dans
`pyproject.toml` : il arrive en dépendance transitive (probablement via `moviepy`).
`<à confirmer>` : le fixer en dépendance directe si l'on veut garantir sa présence.

Le tableau donne les **planchers** déclarés dans `pyproject.toml`, pas les versions
résolues : le `uv.lock` installe aujourd'hui opencv-python **5.0** (branche majeure
suivante) et Streamlit **1.60**. Une exception à connaître : **Pillow reste en 11.3.0**,
plafonné par `moviepy` (qui exige `pillow<12`) — ce n'est pas un choix du projet.

---

## 4. Flux de bout en bout

Parcours type d'un outil de traitement de médias :

1. L'utilisateur choisit un outil dans la barre latérale (navigation `app.py`).
2. La page (`pages/<outil>.py`) collecte un chemin de dossier/fichier et des options.
3. Beaucoup d'outils **prévisualisent** d'abord (calcul sans effet de bord), puis
   **appliquent** sur confirmation. Ex. `files.previsualiser()` → `files.appliquer()`.
4. La logique `tools/` exécute le traitement (ffmpeg, Pillow, pypdf…) et retourne un
   résultat structuré (dataclasses, DataFrame, dict).
5. La page affiche le résultat ; certains outils écrivent un **journal d'annulation**.

```mermaid
flowchart TD
  subgraph UI["pages/ (Streamlit)"]
    p["page outil"]
  end
  subgraph Logique["tools/ (pur, testable)"]
    t["module métier"]
    ff["ffmpeg_utils"]
  end
  subgraph Externe["Binaires / réseau"]
    ffmpeg["ffmpeg embarqué"]
    bm["catalogue BM Lyon"]
  end
  fs[("Dossiers locaux")]
  p -->|chemins + options| t
  t --> ff --> ffmpeg
  t <--> fs
  t -.-> bm
  t -->|résultat| p
```

---

## 5. Sécurité de l'exécution (garde-fous)

L'app agit directement sur le système de fichiers de l'utilisateur ; les protections
sont donc des garde-fous d'**intégrité des données**, pas d'isolation réseau.

| Garde-fou | Effet | Source |
|---|---|---|
| Prévisualisation avant application | L'utilisateur voit les renommages/déplacements avant qu'ils aient lieu | `files.py`, `fonds.py` |
| Journal d'annulation JSON | `annuler()` restaure les noms/emplacements d'origine | `.renommage_undo.json`, `.dedup_undo.json` |
| Non-écrasement | Une cible déjà existante est ignorée, jamais écrasée | `files.appliquer()` |
| ffmpeg embarqué | Pas de binaire système requis ni de PATH à faire confiance | `ffmpeg_utils.py` |
| Imports paresseux des extras | OpenCV / Playwright / Kokoro / CTranslate2 chargés seulement à l'usage | `fonds.py`, `bm_lyon.py`, `tts.py`, `traduction.py`, `transcription.py` |
| Téléchargement atomique des modèles | Écrit dans `*.part` puis renomme : jamais de modèle à moitié écrit | `tts.py`, `traduction.py` |
| Écriture dans un fichier distinct | Le filigrane n'écrase jamais la source : sortie suffixée `_filigrane` | `watermark.py`, pages `*_filigrane.py` |

---

## 6. Décisions d'architecture

- **Séparer `tools/` (pur) et `pages/` (UI)** **plutôt que** mettre la logique dans les
  pages Streamlit, **parce que** la logique redevient testable sans lancer Streamlit
  (cf. `tests/`, dont `test_pages.py` qui ne fait qu'un smoke-test de rendu).
  *Limite* : un peu de code d'enrobage répété dans chaque page.
- **ffmpeg via `imageio-ffmpeg`** **plutôt que** ffmpeg système, **parce que** l'app
  fonctionne sans installation externe.
  *Limite* : dépend d'une version de ffmpeg figée par le paquet.
- **Extras optionnels (`vision`, `scraping`)** **plutôt que** dépendances de base,
  **parce que** OpenCV (~60 Mo) et Playwright (+ navigateur) sont lourds et rarement
  nécessaires. Imports paresseux pour garder la logique testable sans eux.
  *Limite* : un outil non installé échoue à l'usage plutôt qu'au démarrage.
- **Appariement de fonds par SIFT + RANSAC** **plutôt que** un CNN/deep-learning,
  **parce que** la mise en correspondance géométrique suffit (le portrait est un
  recadrage du paysage) et évite `torch`. *Limite* : moins robuste sur des recadrages
  très transformés. (Détails dans la docstring de [`fonds.py`](../tools/fonds.py).)
- **Scraping BM Lyon par recherche de l'artiste seul** (puis filtrage), **parce que**
  l'album précis est mal indexé au catalogue ; matching tolérant (sous-ensemble de nom,
  découpe sur le 1er `" - "`). *Limite* : dépend du HTML du site, fragile aux
  changements (cf. docstring de [`bm_lyon.py`](../tools/bm_lyon.py)).
- **Score de similarité artiste exposé à l'utilisateur** (colonnes « Artiste trouvé » /
  « Score confiance » côté UI) **plutôt que** ne renvoyer qu'un statut binaire trouvé/pas
  trouvé, **parce que** le catalogue nomme parfois artistes et albums de façon trompeuse
  (inversion nom/prénom, nom de scène partiel) : l'utilisateur vérifie à l'œil au lieu de
  faire confiance à un matching qu'il ne peut pas auditer. *Limite* : un score élevé ne
  garantit pas l'absence de faux positif, seulement une similarité textuelle.
- **Synthèse vocale par Kokoro (via `kokoro-onnx`)** **plutôt que** Piper, Chatterbox ou
  XTTS, **parce que** Kokoro donne la voix la plus naturelle tout en tournant sur CPU via
  `onnxruntime` **sans PyTorch** (Chatterbox/XTTS imposent `torch` et visent le GPU), et
  que la phonémisation française passe par espeak-ng **embarqué** (`espeakng-loader`,
  aucune installation système). *Limite* : Kokoro n'offre qu'**une** voix française
  (`ff_siwis`, grade B-) ; pour de la variété de voix FR, Piper serait le complément.
  Le modèle (~340 Mo) n'est pas versionné : il est téléchargé au premier usage.
- **Traduction par NLLB-200 600M via CTranslate2** **plutôt que** par Argos Translate,
  **parce qu'**Argos tire **PyTorch** en dépendance transitive (via `stanza`) et fait
  gonfler l'environnement à **~6 Go** — inacceptable au regard de la charte « léger,
  sans PyTorch ». CTranslate2, lui, est torch-free (inférence CPU quantifiée int8) et
  `transformers` n'est utilisé **que** comme tokenizer. **Plutôt que** OPUS-MT par paire,
  **parce qu'**un **seul** modèle (~623 Mo) couvre **200 langues** — pas de multi-modèles
  ni de pivot. *Limites* : le modèle NLLB est sous licence **CC-BY-NC** (usage **non
  commercial**) ; la variante 600M est un compromis (la 1.3B traduit mieux mais pèse ~3×
  plus) ; qualité variable sur les langues peu dotées. *Alternatives* : OPUS-MT (plus
  léger pour une seule paire), NLLB-1.3B (meilleure qualité, plus lourd).
- **Transcription par faster-whisper (Whisper sur CTranslate2)** **plutôt que**
  `openai-whisper` ou WhisperX, **parce que** ces derniers tirent **PyTorch**, alors que
  faster-whisper réutilise **CTranslate2** — déjà présent (traduction) — donc torch-free,
  CPU int8, ~2× plus rapide. **Plutôt que** whisper.cpp, **parce que** l'intégration
  Python est directe et `av` décode nativement audio **et** vidéo. Le modèle par défaut
  est **large-v3-turbo** (qualité quasi maximale, ~6× plus rapide que large-v3).
  *Limites* : sur CPU, les gros modèles restent lents sur un long fichier ; pas de
  diariation (qui parle) — WhisperX le ferait mais impose torch. *Alternatives* : modèles
  plus petits (`small`/`medium`) pour la vitesse, WhisperX si la diariation devient utile.
- **Filigrane rasterisé (mosaïque Pillow incrustée en image)** **plutôt que** du texte
  vectoriel PDF (`insert_textbox` de PyMuPDF, ou un calque `pypdf`), **parce qu'**un
  **seul** moteur de rendu sert alors aux images **et** aux PDF : rendu strictement
  identique dans les deux cas, un seul chemin de code à tester, et l'angle / l'opacité /
  la mosaïque s'expriment naturellement en RGBA (`Image.alpha_composite`). La mosaïque
  PDF est rendue à **2×** la résolution du point PDF (72 pt/pouce) pour rester nette à
  l'impression. *Limites* : le texte n'est **pas sélectionnable ni recherchable** dans le
  PDF produit, et chaque page gagne une image PNG (fichier plus lourd) ; le filigrane
  reste **retirable** par un éditeur PDF — c'est un **marquage, pas une protection**.
  *Alternative* : texte vectoriel PyMuPDF si la sélectionnabilité ou le poids devient
  déterminant. La police suit une liste de repli (`DejaVuSans-Bold` puis Arial, sinon la
  police Pillow intégrée) : le rendu peut donc varier d'une machine à l'autre.

---

## 7. Limites connues & pistes

| Aspect | Limitation / État | Recommandation |
|---|---|---|
| Scraping BM Lyon | Couplé au HTML du catalogue, `time.sleep` codés en dur, best-effort | Surveiller les changements de sélecteurs ; garder le matching testé |
| Chemins | Saisis en clair, orientés Windows (`M:/…`) | OK pour usage perso ; pas de validation forte |
| `imageio-ffmpeg` | Dépendance transitive non déclarée | La fixer en dépendance directe |
| Tests des pages | Smoke-test de rendu à entrées vides uniquement | Ajouter des tests de bout en bout sur données factices si besoin |
| Synthèse vocale (français) | Une seule voix (`ff_siwis`, grade B-) ; modèle ~340 Mo à télécharger au 1er usage | Ajouter Piper en second moteur si plusieurs voix FR deviennent nécessaires |
| Traduction | Modèle NLLB **CC-BY-NC** (non commercial) ; 600M (compromis qualité) ; ~623 Mo au 1er usage | Passer à NLLB-1.3B ou OPUS-MT selon le besoin qualité/poids |
| Transcription | Lente sur CPU pour les gros modèles / longs fichiers ; pas de diariation | Modèle `small`/`medium` pour la vitesse ; WhisperX (torch) si diariation requise |
| Filigrane | Rasterisé : texte non sélectionnable dans le PDF, +1 image par page ; **marquage, pas protection** (retirable) | Passer au texte vectoriel PyMuPDF si la sélectionnabilité ou le poids devient critique |
| Filigrane — police | Repli `DejaVuSans-Bold` → Arial → police Pillow intégrée : rendu variable selon la machine | Embarquer une police au projet si le rendu doit être reproductible |
| Filigrane — portée | Fichier unique (pas de traitement par dossier) ; PDF filigrané sur **toutes** les pages | Ajouter un mode dossier et une plage de pages si le besoin se confirme |
