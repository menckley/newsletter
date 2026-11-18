# Récap géopolitique

Script Python qui envoie chaque matin par e-mail un récap des 3 sujets géopolitiques et
macro-économiques majeurs de la veille, rédigé en français par Mistral à partir de flux RSS.
Il tourne sur GitHub Actions (`.github/workflows/newsletter.yml`).

## Fonctionnement

1. **Collecte** : lecture des flux RSS de `FLUX_RSS` et conservation des articles publiés la
   veille (fuseau Europe/Paris), dédoublonnés.
2. **Filtrage** : les sujets hors ligne éditoriale (sport, culture…) sont écartés, les autres
   sont classés par mots-clés (politique monétaire en tête). Les 70 meilleurs sont retenus
   (`MAX_ARTICLES_IA`).
3. **Rédaction** : un appel à l'API Mistral (modèle `MISTRAL_MODELE`) choisit les
   `NB_SUJETS` sujets et rédige un point sur chacun, avec les liens des articles sources.
4. **Envoi** : mise en page HTML + texte, envoyée par SMTP. En cas d'échec (moins de
   `MIN_ARTICLES` articles, erreur Mistral…), un e-mail d'alerte est envoyé à la place.

## Planning

Le workflow se lance tous les jours à **5h00, heure de Paris** (`cron: "0 5 * * *"` avec
`timezone: "Europe/Paris"`), ou à la main via « Run workflow » (`workflow_dispatch`).
GitHub peut retarder légèrement les exécutions planifiées.

## Secrets GitHub requis

À définir dans *Settings → Secrets and variables → Actions* :

| Secret | Rôle |
|---|---|
| `MISTRAL_API_KEY` | Clé de l'API Mistral |
| `SMTP_HOST` | Serveur SMTP (défaut du script : `smtp.gmail.com`) |
| `SMTP_PORT` | Port SMTP (défaut : `465` en SSL ; tout autre port utilise STARTTLS) |
| `SMTP_USER` | Identifiant SMTP, aussi expéditeur par défaut |
| `SMTP_PASSWORD` | Mot de passe SMTP (mot de passe d'application pour Gmail) |
| `EMAIL_TO` | Destinataires, séparés par des virgules |

`EMAIL_FROM` (optionnel, variable d'environnement) remplace l'expéditeur ; il n'est pas
transmis par le workflow actuel.

## Modes (variable d'environnement `MODE`)

| Mode | Effet |
|---|---|
| `envoi` (défaut) | Génère le récap et l'envoie par e-mail |
| `apercu` | Génère le récap, l'écrit dans `apercu_recap.html` et l'affiche ; n'envoie rien (appelle Mistral) |
| `sources` | Affiche seulement les 20 premiers articles retenus ; n'appelle ni Mistral ni SMTP |

Le workflow n'injecte pas `MODE` : en production, c'est toujours `envoi`.

## Tester en local

```bash
pip install -r requirements.txt pytest ruff
ruff check .
pytest

MODE=sources python recap_geopolitique.py                          # collecte + filtrage seuls
MISTRAL_API_KEY=... MODE=apercu python recap_geopolitique.py       # rédaction, sans envoi
```

## Coût Mistral

Un seul appel par jour au modèle `ministral-8b-2512`, avec un prompt d'environ 70 articles
(titres et résumés de 300 caractères maximum) et une réponse d'environ 400 mots. Le volume est
très faible ; consulter la grille tarifaire Mistral en vigueur ou la limite de l'offre
gratuite pour le coût exact. En cas de limite (429) ou d'incident (5xx), le script réessaie
pendant 15 minutes au plus (`ATTENTE_MAX_MINUTES`).

## Ajouter un flux RSS

Dans `recap_geopolitique.py`, ajouter une entrée au dictionnaire `FLUX_RSS` :

```python
"Nom affiché": "https://exemple.org/rss.xml",
```

Vérifier ensuite avec `MODE=sources` que le flux apparaît avec un nombre d'articles non nul
(un flux en échec s'affiche `erreur`). Les mots-clés de la ligne éditoriale sont dans
`MOTS_MONETAIRE`, `MOTS_GEOPO` et `MOTS_EXCLUS`.
