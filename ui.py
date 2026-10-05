"""Widgets Streamlit partagés : sélection de fichiers et dossiers.

Sous WSL, les dialogues sont ceux de Windows (appelés via PowerShell), pas ceux de
X11/WSLg : on retrouve l'explorateur habituel, avec les lecteurs et les dossiers
Windows. Les chemins renvoyés (`C:\\...`) sont convertis en chemins WSL
(`/mnt/c/...`) pour que Python puisse les ouvrir.

Hors WSL, on retombe sur tkinter, qui utilise le dialogue natif du système.
"""

from __future__ import annotations

import base64
import functools
import os
import re
import subprocess
import sys
from pathlib import Path

import streamlit as st

# Types de fichiers proposés dans les dialogues, au format tkinter
# (libellé, motifs). Ils sont traduits pour Windows au besoin.
FILETYPES_PDF = [("PDF", "*.pdf"), ("Tous les fichiers", "*.*")]
FILETYPES_VIDEO = [
    ("Vidéos", "*.mp4 *.mkv *.mov *.avi *.webm *.m4v"),
    ("Tous les fichiers", "*.*"),
]
FILETYPES_AUDIO = [
    ("Audio", "*.mp3 *.flac *.m4a *.ogg *.opus *.wav"),
    ("Tous les fichiers", "*.*"),
]
FILETYPES_IMAGE = [
    ("Images", "*.jpg *.jpeg *.png *.bmp *.tiff *.webp"),
    ("Tous les fichiers", "*.*"),
]
FILETYPES_TEXTE = [("Fichier texte", "*.txt"), ("Tous les fichiers", "*.*")]
FILETYPES_CSV = [("CSV", "*.csv"), ("Tous les fichiers", "*.*")]
FILETYPES_TABLEAU = [
    ("Tableaux", "*.csv *.xlsx *.xls *.json"),
    ("Tous les fichiers", "*.*"),
]

_MOTIF_CHEMIN_WINDOWS = re.compile(r"^([A-Za-z]:[\\/]|//|\\\\)")


class ErreurDialogue(RuntimeError):
    """Le dialogue de sélection n'a pas pu s'ouvrir (cause affichée à l'écran)."""


# --------------------------------------------------------------------------- #
# Détection de l'environnement et conversion des chemins
# --------------------------------------------------------------------------- #


@functools.lru_cache(maxsize=1)
def _sous_wsl() -> bool:
    """Vrai si l'app tourne sous WSL avec PowerShell accessible."""
    if sys.platform == "win32" or os.name == "nt":
        return False
    try:
        noyau = Path("/proc/version").read_text(encoding="utf-8").lower()
    except OSError:
        return False
    if "microsoft" not in noyau:
        return False
    try:
        return Path("/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe").is_file()
    except OSError:
        return False


def _convertir_chemin(chemin: str, vers: str) -> str:
    """Convertit un chemin via `wslpath` (« -u » vers WSL, « -w » vers Windows)."""
    if not chemin:
        return ""
    try:
        resultat = subprocess.run(
            ["wslpath", vers, chemin],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        return chemin
    return resultat.stdout.strip() if resultat.returncode == 0 else chemin


def _repli_mnt(chemin_windows: str) -> str:
    """Repli manuel `X:\\a\\b` → `/mnt/x/a/b` quand `wslpath` échoue.

    `wslpath` ne connaît pas les lecteurs réseau mappés (ex. M: → une part SMB,
    ou W: → racine WSL) : on teste d'abord si le chemin correspond directement
    à un dossier WSL existant (ex: W:\\home\\... -> /home/...), sinon on applique
    la convention d'auto-montage de WSL (/mnt/<lettre>/...).
    """
    m = re.match(r"^([A-Za-z]):[\\/](.*)$", chemin_windows)
    if not m:
        return chemin_windows
    lettre, reste = m.group(1).lower(), m.group(2).replace("\\", "/")
    # Si le lecteur pointe directement vers la racine WSL (ex. W:\home\... -> /home/...)
    if reste:
        candidat_racine = f"/{reste}"
        if Path(candidat_racine).exists():
            return candidat_racine
    return f"/mnt/{lettre}/{reste}" if reste else f"/mnt/{lettre}"


def normaliser(chemin: str) -> str:
    """Ramène un chemin Windows (`C:/...`, `W:/...`, `\\\\wsl.localhost\\...`) vers son équivalent WSL."""
    chemin = (chemin or "").strip()
    if chemin and _sous_wsl() and _MOTIF_CHEMIN_WINDOWS.match(chemin):
        converti = _convertir_chemin(chemin.replace("/", "\\"), "-u")
        # wslpath a échoué (lecteur réseau non reconnu) → repli intelligent.
        if _MOTIF_CHEMIN_WINDOWS.match(converti):
            return _repli_mnt(chemin)
        return converti
    return chemin


def _dossier_initial(valeur: str) -> str:
    """Dossier où ouvrir le dialogue, déduit de la valeur courante."""
    valeur = normaliser(valeur)
    if not valeur:
        return ""
    p = Path(valeur)
    if p.is_dir():
        return str(p)
    if p.parent.is_dir():
        return str(p.parent)
    return ""


# --------------------------------------------------------------------------- #
# Dialogues Windows (PowerShell)
# --------------------------------------------------------------------------- #

# Sélecteur de dossier moderne (IFileOpenDialog). PowerShell 5.1 ne propose
# nativement que l'ancien arbre « Rechercher un dossier » : on passe donc par
# l'interface COM utilisée par l'explorateur lui-même.
_INTEROP_DOSSIER = r"""
Add-Type -TypeDefinition @'
using System;
using System.Runtime.InteropServices;

public static class SelecteurDossier
{
    [ComImport, Guid("DC1C5A9C-E88A-4dde-A5A1-60F82A20AEF7")]
    private class FileOpenDialogRCW { }

    [ComImport, Guid("42f85136-db7e-439c-85f1-e4075d135fc8"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IFileDialog
    {
        [PreserveSig] uint Show([In, Optional] IntPtr hwndOwner);
        void SetFileTypes_();
        void SetFileTypeIndex_();
        void GetFileTypeIndex_();
        void Advise_();
        void Unadvise_();
        void SetOptions(uint fos);
        void GetOptions_();
        void SetDefaultFolder_();
        void SetFolder(IShellItem psi);
        void GetFolder_();
        void GetCurrentSelection_();
        void SetFileName_();
        void GetFileName_();
        void SetTitle([MarshalAs(UnmanagedType.LPWStr)] string pszTitle);
        void SetOkButtonLabel_();
        void SetFileNameLabel_();
        void GetResult(out IShellItem ppsi);
    }

    [ComImport, Guid("43826D1E-E718-42EE-BC55-A1E261C37BFE"),
     InterfaceType(ComInterfaceType.InterfaceIsIUnknown)]
    private interface IShellItem
    {
        void BindToHandler_();
        void GetParent_();
        void GetDisplayName(uint sigdnName, out IntPtr ppszName);
        void GetAttributes_();
        void Compare_();
    }

    [DllImport("shell32.dll", CharSet = CharSet.Unicode, PreserveSig = false)]
    private static extern void SHCreateItemFromParsingName(
        [MarshalAs(UnmanagedType.LPWStr)] string pszPath,
        IntPtr pbc,
        [MarshalAs(UnmanagedType.LPStruct)] Guid riid,
        [MarshalAs(UnmanagedType.Interface)] out IShellItem ppv);

    private const uint FOS_PICKFOLDERS = 0x00000020;
    private const uint FOS_FORCEFILESYSTEM = 0x00000040;
    private const uint SIGDN_FILESYSPATH = 0x80058000;

    public static string Choisir(string titre, string dossierInitial, IntPtr proprietaire)
    {
        var dialogue = (IFileDialog)(new FileOpenDialogRCW());
        dialogue.SetOptions(FOS_PICKFOLDERS | FOS_FORCEFILESYSTEM);
        if (!string.IsNullOrEmpty(titre)) { dialogue.SetTitle(titre); }

        if (!string.IsNullOrEmpty(dossierInitial))
        {
            try
            {
                IShellItem depart;
                SHCreateItemFromParsingName(
                    dossierInitial, IntPtr.Zero, typeof(IShellItem).GUID, out depart);
                dialogue.SetFolder(depart);
            }
            catch { /* dossier de depart invalide : on laisse Windows decider */ }
        }

        if (dialogue.Show(proprietaire) != 0) { return ""; }

        IShellItem resultat;
        dialogue.GetResult(out resultat);
        IntPtr pointeur;
        resultat.GetDisplayName(SIGDN_FILESYSPATH, out pointeur);
        string chemin = Marshal.PtrToStringUni(pointeur);
        Marshal.FreeCoTaskMem(pointeur);
        return chemin;
    }
}
'@
"""

# Fenêtre propriétaire, invisible mais centrée à l'écran : le dialogue se
# centre sur elle, et comme elle est « TopMost » il s'ouvre devant le
# navigateur au lieu de rester caché derrière. Placée hors écran, Windows
# rabattait le dialogue dans le coin supérieur gauche, sous le navigateur.
#
# Uniquement des API .NET managées ici : les appels Win32 du type
# SetForegroundWindow via Add-Type sont une signature classique de maliciel et
# se font bloquer par l'antivirus (AMSI), ce qui empêcherait tout le dialogue
# de s'ouvrir.
_FENETRE_AVANT_PLAN = r"""
Add-Type -AssemblyName System.Windows.Forms
Add-Type -AssemblyName System.Drawing
$avantPlan = New-Object System.Windows.Forms.Form
$avantPlan.TopMost = $true
$avantPlan.ShowInTaskbar = $false
$avantPlan.FormBorderStyle = 'None'
$avantPlan.Size = New-Object System.Drawing.Size(1, 1)
$avantPlan.Opacity = 0
$avantPlan.StartPosition = 'CenterScreen'
$avantPlan.Show()
$avantPlan.Activate()
$avantPlan.BringToFront()
"""


def _echapper_ps(valeur: str) -> str:
    """Échappe une chaîne pour l'insérer entre apostrophes en PowerShell."""
    return (valeur or "").replace("'", "''")


def _filtre_windows(filetypes: list[tuple[str, str]]) -> str:
    """Traduit des filetypes tkinter en filtre Win32 (« Libellé (*.x)|*.x|… »)."""
    morceaux = []
    for libelle, motifs in filetypes:
        motifs_ps = ";".join(motifs.split())
        morceaux.append(f"{libelle} ({motifs.replace(' ', ', ')})|{motifs_ps}")
    return "|".join(morceaux)


def _executer_powershell(script: str) -> str:
    """Exécute un script PowerShell et renvoie sa sortie (chemin Windows).

    La sortie est forcée en UTF-8 : sans cela PowerShell écrit dans la page de
    code OEM et les chemins accentués (« Vidéos », « Téléchargements ») seraient
    illisibles. La lecture reste tolérante aux octets invalides, car le flux de
    progression que PowerShell envoie sur stderr n'est pas, lui, en UTF-8.
    """
    entete = (
        "[Console]::OutputEncoding = [System.Text.Encoding]::UTF8\n"
        "$ProgressPreference = 'SilentlyContinue'\n"
    )
    encode = base64.b64encode((entete + script).encode("utf-16-le")).decode("ascii")
    try:
        resultat = subprocess.run(
            [
                "/mnt/c/WINDOWS/System32/WindowsPowerShell/v1.0/powershell.exe",
                "-NoProfile",
                "-STA",
                "-ExecutionPolicy",
                "Bypass",
                "-EncodedCommand",
                encode,
            ],
            capture_output=True,
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        raise ErreurDialogue(
            "Le dialogue est resté ouvert plus de 5 minutes sans réponse. "
            "S'il est masqué derrière une autre fenêtre, ferme-le puis réessaie."
        ) from None
    except (OSError, subprocess.SubprocessError) as e:
        raise ErreurDialogue(f"Impossible de lancer PowerShell : {e}") from e

    sortie = resultat.stdout.decode("utf-8", errors="replace").strip()
    if resultat.returncode != 0:
        erreur = resultat.stderr.decode("cp1252", errors="replace")
        if "ScriptContainedMaliciousContent" in erreur:
            raise ErreurDialogue(
                "L'antivirus a bloqué l'ouverture du dialogue Windows "
                "(AMSI, « contenu malveillant »). Le chemin peut être saisi "
                "manuellement, ou l'antivirus configuré pour autoriser ce script."
            )
        raise ErreurDialogue(f"PowerShell a échoué (code {resultat.returncode}).")

    return sortie.splitlines()[-1].strip() if sortie else ""


def _dialogue_windows(corps: str, dossier_initial: str) -> str:
    """Construit, exécute un dialogue Windows et renvoie un chemin WSL."""
    depart = _convertir_chemin(dossier_initial, "-w") if dossier_initial else ""
    script = "\n".join(
        [
            "$ErrorActionPreference = 'Stop'",
            _FENETRE_AVANT_PLAN,
            f"$depart = '{_echapper_ps(depart)}'",
            corps,
            "$avantPlan.Close()",
            "if ($chemin) { Write-Output $chemin }",
        ]
    )
    return normaliser(_executer_powershell(script))


def _windows_dossier(titre: str, dossier_initial: str) -> str:
    corps = "\n".join(
        [
            _INTEROP_DOSSIER,
            f"$chemin = [SelecteurDossier]::Choisir('{_echapper_ps(titre)}', "
            "$depart, $avantPlan.Handle)",
        ]
    )
    return _dialogue_windows(corps, dossier_initial)


def _windows_fichier(titre: str, dossier_initial: str, filtre: str) -> str:
    corps = "\n".join(
        [
            "$dialogue = New-Object System.Windows.Forms.OpenFileDialog",
            f"$dialogue.Title = '{_echapper_ps(titre)}'",
            f"$dialogue.Filter = '{_echapper_ps(filtre)}'",
            "$dialogue.RestoreDirectory = $true",
            "if ($depart) { $dialogue.InitialDirectory = $depart }",
            "$reponse = $dialogue.ShowDialog($avantPlan)",
            "$chemin = if ($reponse -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ $dialogue.FileName } else { '' }",
        ]
    )
    return _dialogue_windows(corps, dossier_initial)


def _windows_enregistrer(titre: str, dossier_initial: str, nom: str, filtre: str) -> str:
    corps = "\n".join(
        [
            "$dialogue = New-Object System.Windows.Forms.SaveFileDialog",
            f"$dialogue.Title = '{_echapper_ps(titre)}'",
            f"$dialogue.Filter = '{_echapper_ps(filtre)}'",
            f"$dialogue.FileName = '{_echapper_ps(nom)}'",
            "$dialogue.OverwritePrompt = $true",
            "$dialogue.RestoreDirectory = $true",
            "if ($depart) { $dialogue.InitialDirectory = $depart }",
            "$reponse = $dialogue.ShowDialog($avantPlan)",
            "$chemin = if ($reponse -eq [System.Windows.Forms.DialogResult]::OK) "
            "{ $dialogue.FileName } else { '' }",
        ]
    )
    return _dialogue_windows(corps, dossier_initial)


# --------------------------------------------------------------------------- #
# Dialogues de repli (tkinter), hors WSL
# --------------------------------------------------------------------------- #

_TK_DOSSIER = """
import tkinter as tk
from tkinter import filedialog

racine = tk.Tk()
racine.withdraw()
racine.wm_attributes("-topmost", 1)
print(filedialog.askdirectory(title={titre!r}, initialdir={initial!r}) or "", end="")
"""

_TK_FICHIER = """
import tkinter as tk
from tkinter import filedialog

racine = tk.Tk()
racine.withdraw()
racine.wm_attributes("-topmost", 1)
print(
    filedialog.askopenfilename(
        title={titre!r}, initialdir={initial!r}, filetypes={filetypes!r}
    )
    or "",
    end="",
)
"""

_TK_ENREGISTRER = """
import tkinter as tk
from tkinter import filedialog

racine = tk.Tk()
racine.withdraw()
racine.wm_attributes("-topmost", 1)
print(
    filedialog.asksaveasfilename(
        title={titre!r}, initialdir={initial!r},
        initialfile={nom!r}, filetypes={filetypes!r}
    )
    or "",
    end="",
)
"""


def _tk(modele: str, **kwargs) -> str:
    try:
        resultat = subprocess.run(
            [sys.executable, "-c", modele.format(**kwargs)],
            capture_output=True,
            text=True,
            errors="replace",
            timeout=300,
        )
    except (OSError, subprocess.SubprocessError) as e:
        raise ErreurDialogue(f"Le dialogue n'a pas pu s'ouvrir : {e}") from e
    return resultat.stdout.strip()


# --------------------------------------------------------------------------- #
# API publique : ouverture des dialogues
# --------------------------------------------------------------------------- #


def choisir_dossier(valeur_actuelle: str = "", titre: str = "Choisir un dossier") -> str:
    """Ouvre le sélecteur de dossier. Renvoie le chemin choisi, ou "" si annulé."""
    depart = _dossier_initial(valeur_actuelle)
    if _sous_wsl():
        return _windows_dossier(titre, depart)
    return _tk(_TK_DOSSIER, titre=titre, initial=depart)


def choisir_fichier(
    valeur_actuelle: str = "",
    filetypes: list[tuple[str, str]] | None = None,
    titre: str = "Choisir un fichier",
) -> str:
    """Ouvre le sélecteur de fichier. Renvoie le chemin choisi, ou "" si annulé."""
    filetypes = filetypes or [("Tous les fichiers", "*.*")]
    depart = _dossier_initial(valeur_actuelle)
    if _sous_wsl():
        return _windows_fichier(titre, depart, _filtre_windows(filetypes))
    return _tk(_TK_FICHIER, titre=titre, initial=depart, filetypes=filetypes)


def choisir_fichier_sortie(
    valeur_actuelle: str = "",
    filetypes: list[tuple[str, str]] | None = None,
    titre: str = "Enregistrer sous",
) -> str:
    """Ouvre le dialogue « Enregistrer sous ». Renvoie le chemin, ou "" si annulé."""
    filetypes = filetypes or [("Tous les fichiers", "*.*")]
    depart = _dossier_initial(valeur_actuelle)
    nom = Path(valeur_actuelle).name if valeur_actuelle else ""
    if _sous_wsl():
        return _windows_enregistrer(titre, depart, nom, _filtre_windows(filetypes))
    return _tk(_TK_ENREGISTRER, titre=titre, initial=depart, nom=nom, filetypes=filetypes)


# --------------------------------------------------------------------------- #
# API publique : champs de formulaire
# --------------------------------------------------------------------------- #


def _tenter(cle: str, ouvrir, valeur: str) -> None:
    """Ouvre le dialogue et mémorise soit le chemin choisi, soit l'erreur."""
    try:
        choisi = ouvrir(valeur)
    except ErreurDialogue as e:
        st.session_state[f"{cle}__erreur"] = str(e)
        return
    st.session_state.pop(f"{cle}__erreur", None)
    if choisi:
        st.session_state[cle] = choisi
        st.rerun()


def _repli_manuel(cle: str, valeur: str) -> None:
    """Si le dialogue a échoué, affiche l'erreur et permet de saisir le chemin."""
    erreur = st.session_state.get(f"{cle}__erreur")
    if not erreur:
        return
    st.error(erreur, icon="⚠️")
    saisie = st.text_input(
        "Chemin (saisie manuelle, le dialogue étant indisponible)",
        value=valeur,
        key=f"{cle}__manuel",
    )
    if saisie != valeur:
        st.session_state[cle] = normaliser(saisie)
        st.rerun()


def _ligne(label: str, cle: str, texte_vide: str, aide: str | None, ouvrir) -> str:
    """Affiche « label + bouton Parcourir + chemin choisi » sur une ligne."""
    valeur = st.session_state.get(cle, "")

    st.markdown(f"**{label}**")
    largeurs = [1.4, 4, 0.6] if valeur else [1.4, 4.6]
    colonnes = st.columns(largeurs, vertical_alignment="center")

    with colonnes[0]:
        if st.button(
            "📂 Parcourir", key=f"{cle}__parcourir", use_container_width=True, help=aide
        ):
            _tenter(cle, ouvrir, valeur)

    with colonnes[1]:
        if valeur:
            st.code(valeur, language=None, wrap_lines=True)
        else:
            st.caption(texte_vide)

    if valeur:
        with colonnes[2]:
            if st.button("✕", key=f"{cle}__effacer", help="Effacer la sélection"):
                st.session_state[cle] = ""
                st.rerun()

    _repli_manuel(cle, valeur)
    return st.session_state.get(cle, "")


def champ_dossier(
    label: str,
    cle: str,
    valeur_defaut: str = "",
    aide: str | None = None,
    placeholder: str | None = None,  # noqa: ARG001 — conservé pour compatibilité
) -> str:
    """Bouton « Parcourir » pour choisir un dossier, suivi du chemin retenu."""
    if cle not in st.session_state:
        st.session_state[cle] = normaliser(valeur_defaut)
    return _ligne(
        label,
        cle,
        "Aucun dossier sélectionné",
        aide,
        lambda valeur: choisir_dossier(valeur, titre=label),
    )


def champ_fichier(
    label: str,
    cle: str,
    valeur_defaut: str = "",
    filetypes: list[tuple[str, str]] | None = None,
    aide: str | None = None,
    placeholder: str | None = None,  # noqa: ARG001 — conservé pour compatibilité
) -> str:
    """Bouton « Parcourir » pour choisir un fichier, suivi du chemin retenu."""
    if cle not in st.session_state:
        st.session_state[cle] = normaliser(valeur_defaut)
    return _ligne(
        label,
        cle,
        "Aucun fichier sélectionné",
        aide,
        lambda valeur: choisir_fichier(valeur, filetypes=filetypes, titre=label),
    )


def champ_fichier_sortie(
    label: str,
    cle: str,
    valeur_defaut: str = "",
    filetypes: list[tuple[str, str]] | None = None,
    aide: str | None = None,
) -> str:
    """Bouton « Parcourir » ouvrant « Enregistrer sous », suivi du chemin retenu."""
    if cle not in st.session_state:
        st.session_state[cle] = normaliser(valeur_defaut)
    return _ligne(
        label,
        cle,
        "Aucun fichier de destination choisi",
        aide,
        lambda valeur: choisir_fichier_sortie(valeur, filetypes=filetypes, titre=label),
    )


def champ_mixte(
    label: str,
    cle: str,
    valeur_defaut: str = "",
    aide: str | None = None,
    placeholder: str | None = None,  # noqa: ARG001 — conservé pour compatibilité
) -> str:
    """Deux boutons (dossier ou fichier) pour les outils qui acceptent les deux."""
    if cle not in st.session_state:
        st.session_state[cle] = normaliser(valeur_defaut)
    valeur = st.session_state[cle]

    st.markdown(f"**{label}**")
    largeurs = [1.2, 1.2, 3.6, 0.6] if valeur else [1.2, 1.2, 4.2]
    colonnes = st.columns(largeurs, vertical_alignment="center")

    with colonnes[0]:
        if st.button(
            "📁 Dossier", key=f"{cle}__dossier", use_container_width=True, help=aide
        ):
            _tenter(cle, lambda v: choisir_dossier(v, titre=label), valeur)

    with colonnes[1]:
        if st.button("📄 Fichier", key=f"{cle}__fichier", use_container_width=True):
            _tenter(cle, lambda v: choisir_fichier(v, titre=label), valeur)

    with colonnes[2]:
        if valeur:
            st.code(valeur, language=None, wrap_lines=True)
        else:
            st.caption("Aucun fichier ni dossier sélectionné")

    if valeur:
        with colonnes[3]:
            if st.button("✕", key=f"{cle}__effacer", help="Effacer la sélection"):
                st.session_state[cle] = ""
                st.rerun()

    _repli_manuel(cle, valeur)
    return st.session_state.get(cle, "")
