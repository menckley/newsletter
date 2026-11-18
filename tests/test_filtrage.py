"""Filtrage éditorial : normalisation, classement, exclusions."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recap_geopolitique as r  # noqa: E402


def art(titre, resume="", source="Test"):
    return {"source": source, "titre": titre, "resume": resume, "lien": "https://x.test/" + titre}


def test_normaliser_retire_accents_et_casse():
    assert r.normaliser("Réserve FÉDÉRALE") == "reserve federale"


@pytest.mark.parametrize("titre", [
    "Cessez-le-feu à Gaza : les négociations reprennent",
    "Poutine et Zelensky : nouveau sommet",
    "Sanctions contre l'Iran",
    "Oil prices jump as OPEC cuts output",
    "Trump annonce de nouveaux droits de douane",
])
def test_articles_geopolitiques_retenus(titre):
    retenus, ecartes = r.filtrer_articles([art(titre)])
    assert len(retenus) == 1
    assert ecartes == 0
    assert retenus[0]["score"] > 0


@pytest.mark.parametrize("titre", [
    "Football : le PSG remporte le match",
    "Tennis : finale à Roland-Garros",
    "Festival de cinéma : le palmarès",
    "Weather: heavy rain expected this weekend",
])
def test_articles_hors_sujet_ecartes(titre):
    retenus, ecartes = r.filtrer_articles([art(titre)])
    assert retenus == []
    assert ecartes == 1


def test_exclusion_levee_si_mot_cle_geopolitique():
    retenus, _ = r.filtrer_articles([art("Football : la guerre en Ukraine perturbe le match")])
    assert len(retenus) == 1


def test_article_neutre_sans_exclusion_est_conserve():
    retenus, ecartes = r.filtrer_articles([art("Un article quelconque")])
    assert len(retenus) == 1
    assert retenus[0]["score"] == 0
    assert ecartes == 0


def test_politique_monetaire_classee_en_tete_et_marquee():
    articles = [
        art("Guerre en Ukraine, sanctions et embargo"),
        art("La Fed maintient ses taux", source="Le Monde"),
    ]
    retenus, _ = r.filtrer_articles(articles)
    assert retenus[0]["titre"].startswith("La Fed")
    assert retenus[0]["monetaire"] is True
    assert retenus[1]["monetaire"] is False


def test_sources_banques_centrales_toujours_monetaires():
    retenus, _ = r.filtrer_articles([art("Communiqué", source="BCE")])
    assert retenus[0]["monetaire"] is True
    assert retenus[0]["score"] >= 10


def test_ids_sequentiels_apres_classement():
    articles = [art("Rien"), art("Guerre et sanctions"), art("La Fed baisse ses taux")]
    retenus, _ = r.filtrer_articles(articles)
    assert [a["id"] for a in retenus] == [1, 2, 3]
    assert [a["score"] for a in retenus] == sorted((a["score"] for a in retenus), reverse=True)


def test_plafond_articles_ia(monkeypatch):
    monkeypatch.setattr(r, "MAX_ARTICLES_IA", 2)
    retenus, ecartes = r.filtrer_articles([art(f"Guerre {i}") for i in range(5)])
    assert len(retenus) == 2
    assert ecartes == 3


def test_mots_cles_a_frontieres_de_mots():
    # \bfed\b ne doit pas matcher "federation" ; \bwar\b ne doit pas matcher "warm"
    retenus, _ = r.filtrer_articles([art("Federation of warm clubs", "tennis")])
    assert retenus == []
