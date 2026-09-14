import importlib.util

import numpy as np
import pytest

cv2_absent = importlib.util.find_spec("cv2") is None
pytestmark = pytest.mark.skipif(cv2_absent, reason="extra vision (opencv) non installé")

if not cv2_absent:
    import cv2

    from tools import fonds


def _paysage(graine, taille=(800, 450)):
    """Texture unique (nuage basse fréquence + quelques blobs), reproductible.

    Une vraie photo donne des features distinctives ; un motif répétitif
    (mêmes cercles partout) tromperait RANSAC, d'où le nuage propre à chaque graine.
    """
    rng = np.random.default_rng(graine)
    w, h = taille
    petit = rng.integers(0, 255, (h // 16, w // 16, 3), dtype=np.uint8)
    img = cv2.resize(petit, (w, h), interpolation=cv2.INTER_CUBIC)
    for _ in range(25):
        centre = (int(rng.integers(0, w)), int(rng.integers(0, h)))
        rayon = int(rng.integers(6, 22))
        couleur = tuple(int(x) for x in rng.integers(0, 255, 3))
        cv2.circle(img, centre, rayon, couleur, -1)
    return img


def _portrait_depuis(paysage):
    """Recadre une bande verticale et l'agrandit en portrait (zoom)."""
    h, w, _ = paysage.shape
    bande_w = w // 3
    x0 = w // 2 - bande_w // 2
    crop = paysage[:, x0 : x0 + bande_w]
    return cv2.resize(crop, (1080, 1920), interpolation=cv2.INTER_CUBIC)


def _ecrire(chemin, img):
    cv2.imwrite(str(chemin), img)


def test_orientation():
    assert fonds.orientation((1920, 1080)) == "paysage"
    assert fonds.orientation((1080, 1920)) == "portrait"
    assert fonds.orientation((500, 500)) == "carre"


def test_inliers_vrai_vs_faux(tmp_path):
    pa = _paysage(1)
    po = _portrait_depuis(pa)
    autre = _paysage(999)  # sans rapport
    _ecrire(tmp_path / "pa.png", pa)
    _ecrire(tmp_path / "po.png", po)
    _ecrire(tmp_path / "autre.png", autre)

    d_pa = fonds.descripteurs(tmp_path / "pa.png")
    d_po = fonds.descripteurs(tmp_path / "po.png")
    d_autre = fonds.descripteurs(tmp_path / "autre.png")

    vrai = fonds.compter_inliers(d_po, d_pa)
    faux = fonds.compter_inliers(d_po, d_autre)
    assert vrai >= 30  # le vrai recadrage est bien reconnu
    assert faux < vrai  # et nettement au-dessus de l'image sans rapport


def test_apparier_synthetique(tmp_path):
    for n in (1, 2):
        pa = _paysage(n)
        _ecrire(tmp_path / f"pa{n}.png", pa)
        _ecrire(tmp_path / f"po{n}.png", _portrait_depuis(pa))

    res = fonds.apparier(tmp_path, seuil=20)
    assert len(res.couples) == 2
    assert not res.paysages_seuls and not res.portraits_seuls
    # chaque portrait apparié au bon paysage (même numéro)
    for c in res.couples:
        assert (
            c.paysage.name[2] == c.portrait.name[2]
        )  # "pa1"/"po1" → caractère index 2


def test_prochain_id_et_ranger(tmp_path):
    source = tmp_path / "src"
    tries = tmp_path / "tries"
    source.mkdir()
    tries.mkdir()
    (tries / "001_pa.png").write_bytes(b"x")
    (tries / "001_po.png").write_bytes(b"x")
    assert fonds.prochain_id(tries) == 2

    pa = source / "p.png"
    po = source / "q.png"
    _ecrire(pa, _paysage(5))
    _ecrire(po, _portrait_depuis(_paysage(5)))
    couple = fonds.Couple(paysage=pa, portrait=po, score=100, second=2)

    faits = fonds.ranger([couple], tries, deplacer=False)
    assert faits[0][0] == "002"
    assert (tries / "002_pa.png").is_file()
    assert (tries / "002_po.png").is_file()
    assert pa.is_file()  # copie : source conservée


def test_auditer_detecte_erreur(tmp_path):
    # 3 couples : 001 et 002 corrects, 003 volontairement mal classé
    # (003_po est en réalité le portrait du paysage 001).
    pa1, pa2, pa3 = _paysage(1), _paysage(2), _paysage(3)
    _ecrire(tmp_path / "001_pa.png", pa1)
    _ecrire(tmp_path / "001_po.png", _portrait_depuis(pa1))
    _ecrire(tmp_path / "002_pa.png", pa2)
    _ecrire(tmp_path / "002_po.png", _portrait_depuis(pa2))
    _ecrire(tmp_path / "003_pa.png", pa3)
    _ecrire(tmp_path / "003_po.png", _portrait_depuis(pa1))  # erreur : appartient à 001

    suspects = fonds.auditer(tmp_path, seuil_suspect=40)
    erreurs = [s for s in suspects if s.probable_erreur]
    assert any(s.ident == "003" and s.meilleur_ident == "001" for s in erreurs)


def test_audit_cache_et_rapport(tmp_path):
    for n in ("001", "471"):
        _ecrire(tmp_path / f"{n}_pa.png", _paysage(1))
        _ecrire(tmp_path / f"{n}_po.png", _portrait_depuis(_paysage(1)))
    sus = [fonds.Suspect("001", 4, "471", 500)]

    fonds.sauver_audit(sus, tmp_path)
    recharge = fonds.charger_audit(tmp_path)
    assert recharge[0].ident == "001" and recharge[0].probable_erreur

    html = fonds.rapport_html(sus, tmp_path)
    assert "001_po.png" in html and "471_pa.png" in html


def _biblio_dedup(tmp_path):
    # 001 : bon couple unique ; 002 : copie exacte de 001 (doublon complet)
    # 003 : cassé — pa unique (graine 3), po = copie du po de 001 (graine 2)
    _ecrire(tmp_path / "001_pa.png", _paysage(1))
    _ecrire(tmp_path / "001_po.png", _paysage(2))
    _ecrire(tmp_path / "002_pa.png", _paysage(1))
    _ecrire(tmp_path / "002_po.png", _paysage(2))
    _ecrire(tmp_path / "003_pa.png", _paysage(3))
    _ecrire(tmp_path / "003_po.png", _paysage(2))


def test_deduplication_plan(tmp_path):
    _biblio_dedup(tmp_path)
    plan = fonds.plan_deduplication(tmp_path, suspects={"003"}, seuil_hash=4)
    noms_doublons = {f.name for f in plan.doublons}
    noms_verif = {f.name for f in plan.a_verifier}

    assert plan.gardes == ["001"]
    assert {"002_pa.png", "002_po.png", "003_po.png"} <= noms_doublons
    assert "003_pa.png" in noms_verif  # unique → jamais dans Doublons

    plan2 = fonds.plan_deduplication(tmp_path, suspects={"003"}, confirmes_ok={"003"})
    assert "003" in plan2.gardes


def test_deduplication_applique_et_annule(tmp_path):
    _biblio_dedup(tmp_path)
    plan = fonds.plan_deduplication(tmp_path, suspects={"003"})
    fonds.appliquer_deduplication(plan, tmp_path)
    assert (tmp_path / "Doublons" / "002_pa.png").is_file()
    assert (tmp_path / "A_verifier" / "003_pa.png").is_file()
    assert not (tmp_path / "002_pa.png").exists()

    n = fonds.annuler_deduplication(tmp_path)
    assert n >= 3
    assert (tmp_path / "002_pa.png").is_file()
    assert (tmp_path / "003_pa.png").is_file()


def test_lister_png_racine(tmp_path):
    (tmp_path / "img1.png").write_bytes(b"x")
    (tmp_path / "img2.PNG").write_bytes(b"x")
    (tmp_path / "photo.jpg").write_bytes(b"x")
    (tmp_path / "texte.txt").write_bytes(b"x")
    sous_dossier = tmp_path / "SousDossier"
    sous_dossier.mkdir()
    (sous_dossier / "cache.png").write_bytes(b"x")

    fichiers = fonds.lister_png_racine(tmp_path)
    noms = [f.name for f in fichiers]
    assert "img1.png" in noms
    assert "img2.PNG" in noms
    assert "photo.jpg" not in noms
    assert "texte.txt" not in noms
    assert "cache.png" not in noms


def test_signatures_cache(tmp_path):
    d_tries = tmp_path / "tries"
    d_tries.mkdir()
    pa = d_tries / "001_pa.png"
    _ecrire(pa, _paysage(10))

    sigs1, cache_path = fonds.charger_signatures_destination(d_tries)
    assert cache_path.is_file()
    assert "001_pa.png" in sigs1

    # Second appel : réutilise le cache sans recalcul
    sigs2, _ = fonds.charger_signatures_destination(d_tries)
    assert sigs2["001_pa.png"][0] == sigs1["001_pa.png"][0]


def test_preparer_et_appliquer_organisation(tmp_path):
    src = tmp_path / "src"
    tries = tmp_path / "tries"
    src.mkdir()
    tries.mkdir()

    # Destination existante : 001_pa et 001_po
    _ecrire(tries / "001_pa.png", _paysage(1))
    _ecrire(tries / "001_po.png", _portrait_depuis(_paysage(1)))

    # Source :
    # - Un nouveau couple valide (graine 2)
    pa2 = src / "nouveau_pa.png"
    po2 = src / "nouveau_po.png"
    _ecrire(pa2, _paysage(2))
    _ecrire(po2, _portrait_depuis(_paysage(2)))

    # - Un doublon de 001_pa.png (graine 1)
    dup = src / "copie_de_001.png"
    _ecrire(dup, _paysage(1))

    # - Un orphelin sans partenaire (graine 99)
    orph = src / "seul_pa.png"
    _ecrire(orph, _paysage(99))

    # 1. Préparation du plan
    plan = fonds.preparer_organisation(src, tries, seuil_inliers=20)
    assert len(plan.couples) == 1
    assert plan.couples[0].paysage.name == "nouveau_pa.png"
    assert len(plan.doublons) == 1
    assert plan.doublons[0][0].name == "copie_de_001.png"
    assert len(plan.orphelins) == 1
    assert plan.orphelins[0].name == "seul_pa.png"

    # 2. Application de l'organisation (mode déplacement)
    bilan = fonds.appliquer_organisation(plan, tries, deplacer=True)
    assert bilan["premier_id"] == "002"
    assert bilan["dernier_id"] == "002"
    assert (tries / "002_pa.png").is_file()
    assert (tries / "002_po.png").is_file()
    assert (tries / "Doublons" / "copie_de_001.png").is_file()
    assert (tries / "A_verifier" / "seul_pa.png").is_file()
    assert not pa2.exists()
    assert not dup.exists()
    assert not orph.exists()

    # 3. Annulation (rollback)
    nb_restaures = fonds.annuler_organisation(tries)
    assert nb_restaures == 4
    assert pa2.is_file()
    assert po2.is_file()
    assert dup.is_file()
    assert orph.is_file()
