"""Collecte RSS (fixtures locales), nettoyage, dates, dédoublonnage et build_recap."""
import os
import sys
from datetime import date, datetime

import pytest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import recap_geopolitique as r  # noqa: E402

VEILLE = date(2026, 1, 15)


def rss(items):
    corps = "".join(
        f"<item><title>{t}</title><link>{lien}</link><description>{d}</description>"
        f"<pubDate>{pub}</pubDate></item>" for t, lien, d, pub in items)
    return f'<?xml version="1.0"?><rss version="2.0"><channel><title>x</title>{corps}</channel></rss>'.encode()


DANS_LA_VEILLE = "Thu, 15 Jan 2026 10:00:00 GMT"
AUTRE_JOUR = "Mon, 12 Jan 2026 10:00:00 GMT"


class Reponse:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


def test_nettoyer_html_entites_espaces():
    assert r.nettoyer("<p>Hello&nbsp;<b>world</b> &amp;\n  co</p>") == "Hello world & co"


def test_nettoyer_tronque_sur_un_mot():
    res = r.nettoyer("un deux trois quatre", longueur=10)
    assert res == "un deux…"


def test_nettoyer_vide_ou_none():
    assert r.nettoyer("") == ""
    assert r.nettoyer(None) == ""


def test_date_article_convertie_en_heure_de_paris():
    entry = {"published_parsed": (2026, 1, 15, 23, 30, 0, 0, 0, 0)}
    d = r.date_article(entry)
    assert isinstance(d, datetime)
    assert d.date() == date(2026, 1, 16)  # 23h30 UTC = 0h30 à Paris (hiver)


def test_date_article_repli_sur_updated_et_absence():
    assert r.date_article({"updated_parsed": (2026, 1, 15, 10, 0, 0, 0, 0, 0)}).hour == 11
    assert r.date_article({}) is None


def test_lire_flux_ne_garde_que_la_veille_et_les_liens_http(monkeypatch):
    contenu = rss([
        ("Bon", "https://x.test/a", "<b>résumé</b>", DANS_LA_VEILLE),
        ("Ancien", "https://x.test/b", "", AUTRE_JOUR),
        ("Lien invalide", "javascript:alert(1)", "", DANS_LA_VEILLE),
        ("", "https://x.test/c", "", DANS_LA_VEILLE),
    ])
    monkeypatch.setattr(r.requests, "get", lambda *a, **k: Reponse(contenu))
    arts = r.lire_flux("Src", "https://flux.test", VEILLE)
    assert [a["titre"] for a in arts] == ["Bon"]
    assert arts[0]["resume"] == "résumé"
    assert arts[0]["source"] == "Src"


def test_collecter_dedoublonne_et_compte_les_erreurs(monkeypatch):
    flux = {"A": "https://a.test", "B": "https://b.test", "C": "https://c.test"}
    monkeypatch.setattr(r, "FLUX_RSS", flux)
    contenus = {
        "https://a.test": rss([("Même titre !", "https://x.test/1", "", DANS_LA_VEILLE)]),
        # même lien que A, et même titre à la ponctuation près que A
        "https://b.test": rss([("Autre", "https://x.test/1", "", DANS_LA_VEILLE),
                               ("même TITRE", "https://x.test/2", "", DANS_LA_VEILLE),
                               ("Distinct", "https://x.test/3", "", DANS_LA_VEILLE)]),
    }

    def get(url, **kw):
        if url not in contenus:
            raise r.requests.ConnectionError("hors ligne")
        return Reponse(contenus[url])

    monkeypatch.setattr(r.requests, "get", get)
    articles, erreurs, compte = r.collecter_articles(VEILLE)
    assert [a["titre"] for a in articles] == ["Même titre !", "Distinct"]
    assert compte == {"A": 1, "B": 1, "C": "erreur"}
    assert len(erreurs) == 1 and erreurs[0].startswith("C :")


def test_date_fr():
    assert r.date_fr(date(2026, 2, 1)) == "dimanche 1 février 2026"


SUJETS = [{
    "titre": "<script>alert(1)</script>", "zone": "A & B", "theme": "Conflit",
    "point": "<img src=x onerror=alert(1)>",
    "sources": [{"nom": "M\"<b>", "url": 'https://x.test/?a=1&b="2"'}],
}]


def test_build_recap_echappe_le_html_injecte():
    sujet, corps, texte = r.build_recap(SUJETS, VEILLE, ["Média <i>"])
    assert "<script>" not in corps
    assert "<img src=x" not in corps
    assert "&lt;script&gt;" in corps
    assert "A &amp; B" in corps
    assert 'href="https://x.test/?a=1&amp;b=&quot;2&quot;"' in corps
    assert "Média &lt;i&gt;" in corps
    assert "jeudi 15 janvier 2026" in sujet
    assert "jeudi 15 janvier 2026" in texte


def test_build_recap_theme_inconnu_ou_absent():
    s = [{"titre": "T", "point": "P", "sources": []}]
    _, corps, texte = r.build_recap(s, VEILLE, [])
    assert "Pour aller plus loin" not in corps
    assert "border-radius:4px" not in corps  # pas de badge sans thème
    s[0]["theme"] = "Inconnu"
    _, corps, _ = r.build_recap(s, VEILLE, [])
    assert "#6b7280" in corps
    assert "T" in texte


def test_build_erreur_echappe_les_details():
    _, corps, texte = r.build_erreur(VEILLE, "<oops>", "trace <x>")
    assert "&lt;oops&gt;" in corps and "<oops>" not in corps
    assert "<oops>" in texte


@pytest.mark.parametrize("port", [465, 587])
def test_send_email_choisit_le_bon_transport(monkeypatch, port):
    appels = []

    class Faux:
        def __init__(self, host, p, timeout):
            appels.append((type(self).__name__, p))

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def starttls(self):
            pass

        def login(self, *a):
            pass

        def send_message(self, *a):
            pass

    class FauxSSL(Faux):
        pass

    monkeypatch.setattr(r.smtplib, "SMTP_SSL", FauxSSL)
    monkeypatch.setattr(r.smtplib, "SMTP", Faux)
    monkeypatch.setattr(r, "SMTP_USER", "u")
    monkeypatch.setattr(r, "SMTP_PASSWORD", "p")
    monkeypatch.setattr(r, "EMAIL_TO", ["a@x.test"])
    monkeypatch.setattr(r, "SMTP_PORT", port)
    r.send_email("s", "<p>h</p>", "t")
    assert appels == [("FauxSSL" if port == 465 else "Faux", port)]
