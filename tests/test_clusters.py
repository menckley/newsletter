"""Regroupement par événement (optionnel) et passe de vérification."""
import json
import os
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recap_geopolitique as r  # noqa: E402

VEILLE = date(2026, 1, 15)


def art(source, titre, score=1, i=0):
    return {"source": source, "titre": titre, "resume": "résumé", "lien": f"https://x.test/{i}",
            "monetaire": False, "score": score}


def test_titres_proches_regroupes_et_autres_separes():
    a = [art("Le Monde", "Cessez-le-feu à Gaza : négociations reprises au Caire", i=1),
         art("France 24", "Négociations reprises au Caire sur le cessez-le-feu à Gaza", i=2),
         art("Al Jazeera", "Oil prices jump as OPEC cuts output", i=3)]
    groupes = r.regrouper_articles(a)
    assert sorted(len(g) for g in groupes) == [1, 2]
    seul = next(g for g in groupes if len(g) == 1)
    assert seul[0] is a[2]


def test_score_privilegie_nombre_de_medias_distincts():
    plusieurs = [art("A", "x", score=2), art("B", "y", score=2), art("C", "z", score=2)]
    un_seul_riche = [art("A", "x", score=8), art("A", "y", score=8)]
    assert r.score_cluster(plusieurs) > r.score_cluster(un_seul_riche)


def test_classer_par_clusters_numerote_et_ordonne():
    a = [art("A", "Sommet exceptionnel climat", score=1, i=1),
         art("A", "Tempête bourse Tokyo", score=1, i=2),
         art("B", "Bourse Tokyo : tempête et chute", score=1, i=3)]
    res = r.classer_par_clusters(a)
    assert [x["id"] for x in res] == [1, 2, 3]
    assert res[0]["nb_medias"] == 2          # le groupe à 2 médias passe en tête
    assert {x["titre"] for x in res[:2]} == {a[1]["titre"], a[2]["titre"]}


def test_prompt_inchange_sans_cluster():
    a = [{"id": 1, "source": "A", "titre": "T", "resume": "R", "monetaire": False}]
    assert "Même événement" not in r.build_prompt(a, VEILLE)


def test_prompt_avec_cluster_indique_les_medias():
    a = [{"id": 1, "source": "A", "titre": "T", "resume": "R", "monetaire": False,
          "cluster": 1, "nb_medias": 2}]
    assert "2 média(s) distinct(s)" in r.build_prompt(a, VEILLE)


def test_verification_marque_sujet_non_etaye(monkeypatch):
    arts = [{"id": 1, "source": "A", "titre": "T", "resume": "R", "lien": "https://x.test/1"}]
    sujets = [{"point": "p1", "articles": [1]}, {"point": "p2", "articles": [1]}]
    reponse = {"verdicts": [{"sujet": 0, "etaye": True}, {"sujet": 1, "etaye": False}]}
    monkeypatch.setattr(r, "appeler_mistral", lambda p: json.dumps(reponse))
    res = r.verifier_sujets(sujets, arts)
    assert not res[0].get("non_etaye")
    assert res[1]["non_etaye"] is True


def test_verification_tolere_les_erreurs(monkeypatch):
    def boom(p):
        raise RuntimeError("panne")
    monkeypatch.setattr(r, "appeler_mistral", boom)
    sujets = [{"point": "p", "articles": []}]
    assert r.verifier_sujets(sujets, []) == [{"point": "p", "articles": []}]
