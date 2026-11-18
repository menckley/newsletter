"""main() doit envoyer l'e-mail d'erreur puis sortir en code 1."""
import os
import sys

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recap_geopolitique as r  # noqa: E402


def _boom(_veille):
    raise RuntimeError("panne de collecte")


def test_echec_generation_envoie_mail_puis_exit_1(monkeypatch):
    envoyes = []
    monkeypatch.setattr(r, "collecter_articles", _boom)
    monkeypatch.setattr(r, "deliver", lambda *m: envoyes.append(m))
    with pytest.raises(SystemExit) as exc:
        r.main()
    assert exc.value.code == 1
    assert len(envoyes) == 1


def test_succes_ne_quitte_pas_en_erreur(monkeypatch):
    envoyes = []
    monkeypatch.setattr(r, "collecter_articles", lambda v: ([], [], {}))
    monkeypatch.setattr(r, "filtrer_articles", lambda a: ([{}] * 100, 0))
    monkeypatch.setattr(r, "generer_recap", lambda a, v: [])
    monkeypatch.setattr(r, "build_recap", lambda s, v, m: ("sujet", "<p>", "t"))
    monkeypatch.setattr(r, "MIN_ARTICLES", 1)
    monkeypatch.setattr(r, "deliver", lambda *m: envoyes.append(m))
    r.main()
    assert envoyes == [("sujet", "<p>", "t")]
