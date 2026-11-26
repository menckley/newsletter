"""generer_recap : parsing des réponses Mistral (appel réseau simulé)."""
import json
import os
import sys
from datetime import date

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recap_geopolitique as r  # noqa: E402

VEILLE = date(2026, 1, 15)
ARTICLES = [
    {"id": i, "source": f"Média{i}", "lien": f"https://x.test/{i}", "titre": f"T{i}",
     "resume": "", "monetaire": False}
    for i in (1, 2, 3, 4)
]


def sujet(**kw):
    base = {"titre": "Titre", "zone": "Monde", "theme": "Conflit", "point": "Texte", "articles": [1]}
    base.update(kw)
    return base


def repondre(monkeypatch, brut):
    monkeypatch.setattr(r, "appeler_mistral", lambda prompt: brut)


def test_json_simple(monkeypatch):
    repondre(monkeypatch, json.dumps({"sujets": [sujet(articles=[1, 2])]}))
    res = r.generer_recap(ARTICLES, VEILLE)
    assert res[0]["sources"] == [{"nom": "Média1", "url": "https://x.test/1"},
                                 {"nom": "Média2", "url": "https://x.test/2"}]


def test_json_entoure_de_backticks(monkeypatch):
    brut = "```json\n" + json.dumps({"sujets": [sujet()]}) + "\n```"
    repondre(monkeypatch, brut)
    assert len(r.generer_recap(ARTICLES, VEILLE)) == 1


def test_json_precede_de_texte(monkeypatch):
    repondre(monkeypatch, "Voici : " + json.dumps({"sujets": [sujet()]}) + " Cordialement")
    assert len(r.generer_recap(ARTICLES, VEILLE)) == 1


def test_ids_invalides_ignores(monkeypatch):
    s = sujet(articles=[99, "1", None, 2.0, True, 3, -1])
    repondre(monkeypatch, json.dumps({"sujets": [s]}))
    res = r.generer_recap(ARTICLES, VEILLE)
    # True == 1 en Python (bool est un int) : comportement actuel conservé
    assert [src["nom"] for src in res[0]["sources"]] == ["Média1", "Média3"]


def test_maximum_trois_sources_par_sujet(monkeypatch):
    repondre(monkeypatch, json.dumps({"sujets": [sujet(articles=[1, 2, 3, 4])]}))
    assert len(r.generer_recap(ARTICLES, VEILLE)[0]["sources"]) == 3


def test_sujets_incomplets_ignores(monkeypatch):
    sujets = [sujet(titre=""), sujet(point=""), {"zone": "x"}, sujet(titre="Bon")]
    repondre(monkeypatch, json.dumps({"sujets": sujets}))
    res = r.generer_recap(ARTICLES, VEILLE)
    assert [s["titre"] for s in res] == ["Bon"]


def test_limite_nb_sujets(monkeypatch):
    repondre(monkeypatch, json.dumps({"sujets": [sujet(titre=f"S{i}") for i in range(6)]}))
    assert len(r.generer_recap(ARTICLES, VEILLE)) == r.NB_SUJETS


def test_aucun_sujet_exploitable(monkeypatch):
    repondre(monkeypatch, json.dumps({"sujets": []}))
    with pytest.raises(ValueError):
        r.generer_recap(ARTICLES, VEILLE)


def test_json_invalide(monkeypatch):
    repondre(monkeypatch, "pas du json")
    with pytest.raises(json.JSONDecodeError):
        r.generer_recap(ARTICLES, VEILLE)


def test_prompt_contient_articles_et_marque_monetaire():
    arts = [dict(ARTICLES[0], monetaire=True)]
    prompt = r.build_prompt(arts, VEILLE)
    assert "[1] [POLITIQUE MONÉTAIRE] Média1 | T1" in prompt
    assert "jeudi 15 janvier 2026" in prompt


class _Reponse:
    def __init__(self, code, texte="x"):
        self.status_code, self.text, self.ok = code, texte, code < 400


def test_http_402_echoue_immediatement_sans_reessai(monkeypatch):
    appels = []
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: appels.append(1) or _Reponse(402, "billing"))
    monkeypatch.setattr(r.time, "sleep", lambda s: pytest.fail("ne doit pas attendre"))
    with pytest.raises(PermissionError, match="402"):
        r.appeler_mistral("prompt")
    assert len(appels) == 1


def test_http_503_est_reessaye(monkeypatch):
    monkeypatch.setattr(r.requests, "post", lambda *a, **k: _Reponse(503))
    monkeypatch.setattr(r.time, "sleep", lambda s: None)
    monkeypatch.setattr(r, "ATTENTE_MAX_MINUTES", 0)
    with pytest.raises(RuntimeError, match="n'a pas répondu"):
        r.appeler_mistral("prompt")
