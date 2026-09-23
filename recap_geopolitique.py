#!/usr/bin/env python3
"""
Récap géopolitique quotidien : flux RSS + Mistral + e-mail — VERSION GITHUB ACTIONS.

Chaque exécution :
  1. récupère les articles publiés la veille dans les flux RSS de FLUX_RSS ;
  2. filtre et classe les articles selon la ligne éditoriale (mots-clés prioritaires,
     exclusion du sport, de la culture, etc.) ;
  3. demande à Mistral d'en tirer les 3 sujets majeurs et de faire le point sur chacun ;
  4. met le résultat en page et l'envoie par e-mail (ou un e-mail d'alerte en cas d'échec).

Paramètres lus dans les variables d'environnement (Secrets GitHub) :
  MISTRAL_API_KEY, SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD,
  EMAIL_TO (adresses séparées par des virgules), MODE (optionnel, "envoi" par défaut).
"""
from __future__ import annotations

import html
import os
import json
import re
import smtplib
import time
import traceback
import unicodedata
from datetime import date, datetime, timedelta, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from zoneinfo import ZoneInfo

import feedparser
import requests

# =============================================================================
# CONFIGURATION
# =============================================================================
MODE = os.getenv("MODE", "envoi").strip().lower()   # "sources", "apercu" ou "envoi"

# --- Mistral ---
MISTRAL_API_KEY = os.getenv("MISTRAL_API_KEY", "")
MISTRAL_MODELE = "ministral-8b-2512"
ATTENTE_MAX_MINUTES = 15   # durée maximale des nouvelles tentatives si Mistral refuse (429, 5xx)
NB_SUJETS = 3

# --- Flux RSS (nom affiché : adresse du flux) ---
FLUX_RSS = {
    "Le Monde":           "https://www.lemonde.fr/international/rss_full.xml",
    "Le Monde Économie":  "https://www.lemonde.fr/economie/rss_full.xml",
    "Le Figaro":          "https://www.lefigaro.fr/rss/figaro_international.xml",
    "France 24":          "https://www.france24.com/fr/rss",
    "BBC News":           "https://feeds.bbci.co.uk/news/world/rss.xml",
    "BBC Business":       "https://feeds.bbci.co.uk/news/business/rss.xml",
    "The Guardian":       "https://www.theguardian.com/world/rss",
    "Guardian Business":  "https://www.theguardian.com/business/rss",
    "Al Jazeera":         "https://www.aljazeera.com/xml/rss/all.xml",
    "BCE":                "https://www.ecb.europa.eu/rss/press.html",
    "Réserve fédérale":   "https://www.federalreserve.gov/feeds/press_monetary.xml",
}
MAX_ARTICLES_PAR_FLUX = 40
MAX_ARTICLES_IA = 70      # nombre d'articles (les mieux classés) transmis à Mistral
MIN_ARTICLES = 8          # en dessous, on considère que la collecte a échoué
FUSEAU = ZoneInfo("Europe/Paris")

# --- Ligne éditoriale : mots-clés (sans accents, en minuscules ; expressions régulières) ---
# Politique monétaire : un article qui en parle est toujours transmis en tête de liste.
MOTS_MONETAIRE = [
    r"taux directeur", r"interest rates?", r"rate (cut|hike|decision)", r"banques? centrales?",
    r"central banks?", r"\bbce\b", r"\becb\b", r"\bfed\b", r"federal reserve", r"reserve federale",
    r"bank of england", r"bank of japan", r"\bboj\b", r"banque du japon", r"\bpboc\b",
    r"politique monetaire", r"monetary policy", r"lagarde", r"powell",
]
# Enjeux géopolitiques et macro-économiques.
MOTS_GEOPO = [
    # Moyen-Orient
    r"moyen.orient", r"middle east", r"israel", r"gaza", r"hamas", r"hezbollah", r"liban",
    r"lebanon", r"\biran", r"syri", r"yemen", r"houthi", r"arabie saoudite", r"saudi", r"\birak",
    r"\biraq", r"qatar", r"emirats", r"\buae\b", r"cisjordanie", r"west bank", r"jordan",
    r"egypt", r"turqui", r"turkey", r"erdogan", r"netanyahou", r"netanyahu", r"golfe", r"\bgulf\b",
    # Grandes puissances et conflits
    r"ukrain", r"russi", r"poutine", r"putin", r"zelensky", r"kremlin", r"\bchin[ae]\b",
    r"chinois", r"chinese", r"taiwan", r"xi jinping", r"coree du nord", r"north korea",
    r"\botan\b", r"\bnato\b", r"maison blanche", r"white house", r"trump", r"pentagon",
    # Diplomatie, sécurité, politique
    r"sanction", r"embargo", r"cessez.le.feu", r"ceasefire", r"missile", r"frappes?\b",
    r"\bstrikes?\b", r"nucleaire", r"nuclear", r"diplomat", r"sommet", r"summit", r"\bg7\b",
    r"\bg20\b", r"\bonu\b", r"united nations", r"conseil de securite", r"security council",
    r"elections?\b", r"coup d.etat", r"\bcoup\b", r"guerre", r"\bwar\b", r"invasion",
    # Économie mondiale et matières premières
    r"droits de douane", r"tarifs?\b", r"tariffs?", r"guerre commerciale", r"trade war",
    r"\bopep", r"\bopec", r"petrole", r"\boil\b", r"\bbrent\b", r"\bgaz\b", r"\bgas\b",
    r"inflation", r"recession", r"dette", r"\bdebt\b", r"marches financiers", r"markets?\b",
]
# Sujets écartés (sauf si l'article contient aussi un mot-clé ci-dessus).
MOTS_EXCLUS = [
    r"football", r"ligue 1", r"ligue des champions", r"champions league", r"premier league",
    r"tennis", r"rugby", r"formule 1", r"formula (one|1)", r"olympi", r"\bmatch\b", r"mercato",
    r"transfert", r"\bnba\b", r"cricket", r"tour de france", r"festival", r"cinema", r"\bfilm",
    r"album", r"concert", r"box.office", r"horoscope", r"recette", r"meteo", r"weather",
    r"celebrit", r"royal family", r"fashion", r"\bmode\b",
]

# --- Envoi de l'e-mail ---
SMTP_HOST = os.getenv("SMTP_HOST") or "smtp.gmail.com"
SMTP_PORT = int(os.getenv("SMTP_PORT") or 465)
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
EMAIL_FROM = os.getenv("EMAIL_FROM") or SMTP_USER
EMAIL_TO = [a.strip() for a in os.getenv("EMAIL_TO", "").split(",") if a.strip()]

JOURS_FR = ["lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche"]
MOIS_FR = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet",
           "août", "septembre", "octobre", "novembre", "décembre"]
HEADERS = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_0) recap-geopolitique/1.0"}


def date_fr(d: date) -> str:
    return f"{JOURS_FR[d.weekday()]} {d.day} {MOIS_FR[d.month - 1]} {d.year}"


# =============================================================================
# COLLECTE DES FLUX RSS
# =============================================================================
def nettoyer(texte: str, longueur: int = 300) -> str:
    """Retire le HTML et raccourcit un résumé d'article."""
    t = html.unescape(re.sub(r"<[^>]+>", " ", texte or ""))
    t = re.sub(r"\s+", " ", t).strip()
    return t if len(t) <= longueur else t[:longueur].rsplit(" ", 1)[0] + "…"


def date_article(entry) -> datetime | None:
    struct = entry.get("published_parsed") or entry.get("updated_parsed")
    if not struct:
        return None
    return datetime(*struct[:6], tzinfo=timezone.utc).astimezone(FUSEAU)


def lire_flux(nom: str, url: str, veille: date) -> list[dict]:
    r = requests.get(url, headers=HEADERS, timeout=20)
    r.raise_for_status()
    flux = feedparser.parse(r.content)
    articles = []
    for entry in flux.entries[:MAX_ARTICLES_PAR_FLUX]:
        publie = date_article(entry)
        if publie is None or publie.date() != veille:
            continue
        titre, lien = nettoyer(entry.get("title", ""), 200), entry.get("link", "")
        if titre and lien.startswith("http"):
            articles.append({"source": nom, "titre": titre, "lien": lien,
                             "resume": nettoyer(entry.get("summary", ""))})
    return articles


def collecter_articles(veille: date) -> tuple[list[dict], list[str], dict]:
    """Renvoie (articles de la veille, erreurs, nombre d'articles par flux)."""
    articles, erreurs, compte, vus = [], [], {}, set()
    for nom, url in FLUX_RSS.items():
        try:
            trouves = lire_flux(nom, url, veille)
        except Exception as e:
            erreurs.append(f"{nom} : {e}")
            compte[nom] = "erreur"
            continue
        nouveaux = 0
        for a in trouves:
            cle = re.sub(r"\W+", "", a["titre"].lower())
            if a["lien"] in vus or cle in vus:
                continue
            vus.update({a["lien"], cle})
            articles.append(a)
            nouveaux += 1
        compte[nom] = nouveaux
    return articles, erreurs, compte


# =============================================================================
# FILTRAGE ÉDITORIAL
# =============================================================================
def normaliser(texte: str) -> str:
    """Minuscules sans accents, pour comparer avec les mots-clés."""
    t = unicodedata.normalize("NFKD", texte.lower())
    return "".join(c for c in t if not unicodedata.combining(c))


def compter(texte: str, motifs: list[str]) -> int:
    return sum(1 for m in motifs if re.search(m, texte))


def filtrer_articles(articles: list[dict]) -> tuple[list[dict], int]:
    """Écarte les sujets hors ligne éditoriale et classe les autres par pertinence.
    Renvoie (articles retenus numérotés, nombre d'articles écartés)."""
    retenus, ecartes = [], 0
    for a in articles:
        texte = normaliser(f"{a['titre']} {a['resume']}")
        monetaire, geopo = compter(texte, MOTS_MONETAIRE), compter(texte, MOTS_GEOPO)
        if monetaire + geopo == 0 and compter(texte, MOTS_EXCLUS):
            ecartes += 1
            continue
        a["monetaire"] = monetaire > 0 or a["source"] in ("BCE", "Réserve fédérale")
        a["score"] = 10 * a["monetaire"] + geopo
        retenus.append(a)
    retenus.sort(key=lambda a: a["score"], reverse=True)
    ecartes += max(0, len(retenus) - MAX_ARTICLES_IA)
    retenus = retenus[:MAX_ARTICLES_IA]
    for i, a in enumerate(retenus, 1):
        a["id"] = i
    return retenus, ecartes


# =============================================================================
# RÉDACTION PAR MISTRAL
# =============================================================================
SYSTEM = ("Tu es un analyste en géopolitique et en macro-économie qui rédige chaque matin une "
          "revue d'actualité en français pour un lecteur averti, intéressé par tout ce qui fait "
          "bouger l'équilibre du monde. Ton style est clair, factuel et neutre : tu n'exprimes pas "
          "d'opinion et tu attribues les déclarations à leurs auteurs.")


def build_prompt(articles: list[dict], veille: date) -> str:
    liste = "\n".join(
        f"[{a['id']}]{' [POLITIQUE MONÉTAIRE]' if a['monetaire'] else ''} {a['source']} | "
        f"{a['titre']} | {a['resume']}" for a in articles)
    return f"""Voici des articles d'actualité publiés le {date_fr(veille)} (numéro, média, titre, résumé), classés du plus pertinent au moins pertinent :

{liste}

LIGNE ÉDITORIALE — choisis les {NB_SUJETS} sujets qui font le plus bouger la géopolitique mondiale ce jour-là :
- Priorité absolue : si une grande banque centrale (Fed, BCE, Banque d'Angleterre, Banque du Japon, Banque populaire de Chine…) a MODIFIÉ ses taux directeurs, ce doit être l'un des sujets. Une simple déclaration ou un maintien des taux n'est retenu que s'il est majeur.
- Les événements du Moyen-Orient (conflits, négociations, tensions régionales).
- Les rapports de force entre grandes puissances : États-Unis, Chine, Russie, Europe ; guerres, sanctions, droits de douane, accords, sommets.
- Les chocs économiques à portée géopolitique : pétrole et énergie, commerce mondial, crises de dette, marchés.
- Les crises politiques majeures : élections décisives, coups d'État, chutes de gouvernement.
Ignore le sport, la culture, les faits divers et l'actualité purement nationale sans portée internationale.
Un sujet traité par plusieurs médias est généralement plus important. Les trois sujets doivent être distincts : pas deux sujets sur le même conflit ou le même événement.

RÉDACTION — pour chaque sujet, un point de 90 à 130 mots en français :
1. ce qui s'est passé ;
2. le contexte indispensable ;
3. pourquoi c'est important : conséquences géopolitiques, et le cas échéant économiques ou financières (marchés, énergie, taux).
Les faits doivent provenir des articles. Tu peux ajouter un contexte général bien établi, mais aucun fait nouveau. Rédige avec tes propres mots.

Pour chaque sujet, indique dans "articles" les numéros des 1 à 3 articles qui le traitent le mieux. "titre" : court et informatif, en français. "zone" : la région ou le pays concerné. "theme" : un mot parmi Conflit, Diplomatie, Finance, Économie, Énergie, Politique.

Réponds uniquement avec un objet JSON valide, au format :
{{"sujets": [{{"titre": "...", "zone": "...", "theme": "...", "point": "...", "articles": [1, 2]}}]}}"""


def appeler_mistral(prompt: str) -> str:
    """Appelle Mistral ; en cas de limite (429) ou d'incident (5xx), patiente et recommence."""
    debut, pause = time.monotonic(), 65
    while True:
        try:
            r = requests.post(
                "https://api.mistral.ai/v1/chat/completions", timeout=120,
                headers={"Authorization": f"Bearer {MISTRAL_API_KEY}"},
                json={"model": MISTRAL_MODELE, "temperature": 0.3,
                      "response_format": {"type": "json_object"},
                      "messages": [{"role": "system", "content": SYSTEM},
                                   {"role": "user", "content": prompt}]})
            if r.ok:
                return r.json()["choices"][0]["message"]["content"]
            if r.status_code in (400, 401, 403, 404, 422):  # erreur définitive : inutile d'insister
                raise PermissionError(f"Mistral a refusé la requête (HTTP {r.status_code}) : {r.text[:200]}")
            erreur = f"HTTP {r.status_code} : {r.text[:150]}"
        except requests.RequestException as e:  # coupure réseau, délai dépassé…
            erreur = str(e)[:150]
        if time.monotonic() - debut + pause > ATTENTE_MAX_MINUTES * 60:
            raise RuntimeError(f"Mistral n'a pas répondu après {ATTENTE_MAX_MINUTES} min : {erreur}")
        print(f"Mistral : {erreur} → nouvel essai dans {pause} s…")
        time.sleep(pause)
        pause = min(pause * 2, 240)


def generer_recap(articles: list[dict], veille: date) -> list[dict]:
    texte = re.sub(r"```(?:json)?", "", appeler_mistral(build_prompt(articles, veille)))
    donnees = json.loads(texte[texte.find("{"):texte.rfind("}") + 1])
    par_id = {a["id"]: a for a in articles}
    sujets = []
    for s in donnees.get("sujets", []):
        if not (s.get("titre") and s.get("point")):
            continue
        ids = [i for i in s.get("articles", []) if isinstance(i, int) and i in par_id][:3]
        s["sources"] = [{"nom": par_id[i]["source"], "url": par_id[i]["lien"]} for i in ids]
        sujets.append(s)
    if not sujets:
        raise ValueError("aucun sujet exploitable dans la réponse de Mistral")
    return sujets[:NB_SUJETS]


# =============================================================================
# MISE EN FORME DE L'E-MAIL
# =============================================================================
COULEURS_THEME = {"conflit": "#b91c1c", "diplomatie": "#1d4ed8", "finance": "#047857",
                  "economie": "#0f766e", "energie": "#b45309", "politique": "#6d28d9"}


def build_recap(sujets: list[dict], veille: date, medias: list[str]) -> tuple[str, str, str]:
    subject = f"🌍 Récap géopolitique – {date_fr(veille)}"
    cartes, lignes = [], []
    for i, s in enumerate(sujets, 1):
        titre, zone, point, theme = (html.escape(str(s.get(k, "")))
                                     for k in ("titre", "zone", "point", "theme"))
        couleur = COULEURS_THEME.get(normaliser(theme), "#6b7280")
        badge = (f'<span style="background:{couleur};color:#fff;border-radius:4px;padding:2px 6px;'
                 f'margin-right:6px;">{theme}</span>') if theme else ""
        liens = " · ".join(f'<a href="{html.escape(src["url"])}" style="color:#2563eb;">'
                           f'{html.escape(src["nom"])}</a>' for src in s["sources"])
        cartes.append(f"""
<div style="margin:0 0 20px 0;padding:16px 18px;border:1px solid #e5e7eb;border-radius:8px;">
  <div style="font-size:12px;color:#6b7280;text-transform:uppercase;letter-spacing:.05em;">{badge}{i} · {zone}</div>
  <h3 style="margin:8px 0 10px 0;font-size:17px;">{titre}</h3>
  <p style="margin:0 0 10px 0;line-height:1.55;">{point}</p>
  {f'<div style="font-size:13px;color:#555;">Pour aller plus loin : {liens}</div>' if liens else ''}
</div>""")
        sources_txt = "\n".join(f"   - {src['nom']} : {src['url']}" for src in s["sources"])
        lignes.append(f"{i}. [{s.get('theme', '')}] {s.get('titre', '')} ({s.get('zone', '')})\n"
                      f"{s.get('point', '')}\n{sources_txt}")

    pied = (f"Rédigé automatiquement par une IA (Mistral {MISTRAL_MODELE}) à partir des flux RSS de : "
            f"{', '.join(medias)}.")
    html_body = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#111;margin:0;padding:16px;max-width:680px;">
<h2 style="margin:0 0 4px 0;font-size:21px;">Récap géopolitique</h2>
<p style="margin:0 0 20px 0;color:#555;">Les {len(sujets)} sujets du {date_fr(veille)}</p>
{''.join(cartes)}
<p style="font-size:12px;color:#888;">{html.escape(pied)}<br>
Une IA peut commettre des erreurs : consulte les articles pour vérifier.</p>
</body></html>"""
    texte = f"Récap géopolitique – {date_fr(veille)}\n\n" + "\n\n".join(lignes) + f"\n\n{pied}"
    return subject, html_body, texte


def build_erreur(veille: date, erreur: str, details: str) -> tuple[str, str, str]:
    subject = f"⚠️ Récap géopolitique du {veille:%d/%m/%Y} indisponible"
    html_body = f"""<html><body style="font-family:Arial,Helvetica,sans-serif;color:#111;padding:16px;">
<h2 style="margin:0 0 12px 0;font-size:20px;color:#c62828;">Récap non généré</h2>
<p>Le récap géopolitique du {date_fr(veille)} n'a pas pu être généré.</p>
<p><b>Erreur :</b> {html.escape(erreur)}</p>
<pre style="font-size:11px;background:#f3f4f6;padding:10px;white-space:pre-wrap;">{html.escape(details)}</pre>
<p style="font-size:12px;color:#888;">Causes possibles : flux RSS indisponibles ou modifiés, clé Mistral
invalide, limite de l'offre gratuite atteinte, indisponibilité prolongée de Mistral.</p>
</body></html>"""
    texte = f"Le récap géopolitique du {date_fr(veille)} n'a pas pu être généré.\n\nErreur : {erreur}\n\n{details}"
    return subject, html_body, texte


# =============================================================================
# ENVOI
# =============================================================================
def send_email(subject: str, html_body: str, texte: str) -> None:
    if not (SMTP_USER and SMTP_PASSWORD and EMAIL_TO):
        raise smtplib.SMTPException("SMTP_USER, SMTP_PASSWORD ou EMAIL_TO manquant (Secrets GitHub)")
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = EMAIL_FROM
    msg["To"] = ", ".join(EMAIL_TO)
    msg["Date"] = formatdate(localtime=True)
    msg.attach(MIMEText(texte, "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    host, port = SMTP_HOST.strip(), int(SMTP_PORT)
    if port == 465:
        with smtplib.SMTP_SSL(host, port, timeout=30) as smtp:
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg, EMAIL_FROM, EMAIL_TO)
    else:
        with smtplib.SMTP(host, port, timeout=30) as smtp:
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.send_message(msg, EMAIL_FROM, EMAIL_TO)


def deliver(subject: str, html_body: str, texte: str) -> None:
    if MODE == "apercu":
        with open("apercu_recap.html", "w", encoding="utf-8") as f:
            f.write(html_body)
        print(f"\nObjet : {subject}\n\n{texte}\n\n→ Aperçu enregistré dans apercu_recap.html (rien n'a été envoyé)")
    else:
        send_email(subject, html_body, texte)
        print(f"E-mail envoyé : {subject}")


# =============================================================================
# PROGRAMME PRINCIPAL
# =============================================================================
def main() -> None:
    veille = datetime.now(FUSEAU).date() - timedelta(days=1)
    try:
        articles, erreurs, compte = collecter_articles(veille)
        print(f"Articles du {veille:%d/%m/%Y} : " + ", ".join(f"{k} {v}" for k, v in compte.items()))
        for e in erreurs:
            print(f"  [!] {e}")
        retenus, ecartes = filtrer_articles(articles)
        print(f"Filtrage : {len(retenus)} articles retenus, {ecartes} écartés")
        if MODE == "sources":
            for a in retenus[:20]:
                marque = " [MONÉTAIRE]" if a["monetaire"] else ""
                print(f"  [{a['id']}] score {a['score']}{marque} | {a['source']} | {a['titre']}")
            return
        if len(retenus) < MIN_ARTICLES:
            raise ValueError(f"seulement {len(retenus)} articles pertinents trouvés dans les flux RSS")
        sujets = generer_recap(retenus, veille)
        medias = [nom for nom, n in compte.items() if n not in (0, "erreur")]
        message = build_recap(sujets, veille, medias)
    except Exception as e:
        message = build_erreur(veille, str(e), traceback.format_exc())
    try:
        deliver(*message)
    except (smtplib.SMTPException, OSError) as e:
        raise SystemExit(f"\nÉchec de l'envoi de l'e-mail via {SMTP_HOST}:{SMTP_PORT} → {e!r}")


if __name__ == "__main__":
    main()
