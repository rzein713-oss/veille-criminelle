#!/usr/bin/env python3
"""Collecte quotidienne pour Veille criminelle Québec.

Lit des fils RSS publics (CanLII, Cour suprême, LEGISinfo, Droit-inc, ABC,
Google Actualités), garde ce qui touche le droit criminel, et met à jour
data/items.json. Aucune dépendance externe : bibliothèque standard seulement.
"""
import datetime as dt
import email.utils
import html
import json
import os
import re
import sys
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "items.json")
KEEP_DAYS = 120          # durée de conservation sur le site
WINDOW_DAYS = 14         # n'ajoute que des éléments récents
UA = "Mozilla/5.0 (compatible; RevueCriminellePenaleQC/1.0; +https://subrosaconnect.ca)"
TODAY = dt.datetime.now(dt.timezone(dt.timedelta(hours=-5))).date()  # heure de l'Est (approx.)

CRIM_DESC = re.compile(
    r"Infractions criminelles|Droit criminel|Code criminel|C\.cr\.|LSJPA|justice pénale pour les adolescents"
    r"|Code de procédure pénale|Charte canadienne|Détermination de la peine|Mise en liberté provisoire"
    r"|Infractions réglementaires|infraction pénale|poursuite pénale|droit pénal|constat d.infraction|Code de la sécurité routière",
    re.I)
CRIM_TITLE = re.compile(r"(^|\s)R\. c\.|c\. R\.|LSJPA|Directeur des poursuites criminelles|\bDPCP\b|c\. Sa Majesté", re.I)
LEGIS_KW = re.compile(
    r"criminel|pénal|peine|casier|libération|mise en liberté|caution|drogue|stupéfiant|arme|"
    r"adolescent|victime|terroris|exploitation|traite|violence|police|correctionnel|blanchiment|fraude|"
    r"infraction|amende|contravention|sanction",
    re.I)
PRO_KW = re.compile(
    r"criminel|pénal|\bDPCP\b|AQAAD|avocats? de la défense|accusée?s?\b|procès|détention|prison|détenu|"
    r"\bpeine|Barreau du Québec|radiée?|déontolog|aide juridique|\bJordan\b|LSJPA|policier|\bBEI\b|meurtre|agression",
    re.I)

CANLII = [
    ("qcca", "Cour d'appel du Québec"),
    ("qccs", "Cour supérieure"),
    ("qccq", "Cour du Québec – chambre criminelle et pénale"),
    ("qccm", "Cour municipale"),
]

NEWS = {
    "Politique et justice": [
        '"Code criminel" projet de loi', '"ministre de la Justice" Québec criminel',
        '"mise en liberté sous caution"', 'AQAAD OR "avocats de la défense" Québec', '"arrêt Jordan" OR "délais déraisonnables"',
    ],
    "Système carcéral": [
        '"centre de détention" Québec', '"Service correctionnel" Canada détenu', '"libération conditionnelle" Québec',
    ],
    "Police et enquêtes": [
        'SPVM arrestation', '"Sûreté du Québec" enquête', '"Bureau des enquêtes indépendantes"', 'UPAC',
    ],
    "Crimes et procès": [
        '"palais de justice" Québec accusé', '"reconnu coupable" Québec', 'procès meurtre Québec', '"Chambre de la jeunesse" OR LSJPA',
    ],
    "Tendances et société": [
        '"crime organisé" Québec', '"violence conjugale" tribunal Québec', '"aide juridique" Québec',
    ],
    "Droit pénal et réglementaire": [
        '"constat d\'infraction" Québec tribunal', '"Code de la sécurité routière" cour OR amende',
        '"poursuite pénale" OR "infraction pénale" Québec', '"cour municipale" Québec', 'DPCP amende entreprise',
    ],
}


def log(*a):
    print(*a, file=sys.stderr)


def fetch(url, tries=3):
    req = urllib.request.Request(url, headers={"User-Agent": UA, "Accept": "application/rss+xml, application/xml, text/xml, */*"})
    for n in range(tries):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                return r.read()
        except Exception:  # noqa: BLE001
            if n == tries - 1:
                raise
            time.sleep(5 * (n + 1))


def items_of(xml_bytes):
    root = ET.fromstring(xml_bytes)
    return list(root.iter("item"))


def text(el, tag):
    return (el.findtext(tag) or "").strip()


def clean(s):
    s = re.sub(r"<br\s*/?>", " — ", s or "", flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = html.unescape(s)
    return re.sub(r"\s+", " ", s).strip()


def pub_date(s):
    if not s:
        return None
    try:
        return email.utils.parsedate_to_datetime(s).date()
    except (TypeError, ValueError):
        return None


def recent(d):
    return d is not None and (TODAY - d).days <= WINDOW_DAYS


def cut(s, n=420):
    return s if len(s) <= n else s[: n - 1].rsplit(" ", 1)[0] + "…"


# ---------- Sources ----------

def from_canlii():
    out = []
    for db, court in CANLII:
        try:
            its = items_of(fetch(f"https://www.canlii.org/fr/qc/{db}/rss_new.xml"))
        except Exception as e:  # noqa: BLE001
            log("CanLII", db, "échec:", e)
            continue
        for it in its:
            title, desc = clean(text(it, "title")), clean(text(it, "description"))
            d = pub_date(text(it, "pubDate"))
            if not recent(d):
                continue
            if "Droit de la famille" in title:
                continue
            crim = CRIM_TITLE.search(title) or CRIM_DESC.search(desc)
            if not crim:
                continue
            tribunal = court
            if db == "qccq" and re.search(r"LSJPA|adolescent", title + desc, re.I):
                tribunal = "Chambre de la jeunesse"
            m = re.search(r"(\d{4} QC[A-Z]+ \d+)", title)
            name = re.sub(r",?\s*\d{4} QC[A-Z]+ \d+.*$", "", title).strip()
            out.append({
                "col": "decisions", "titre": name or title, "reference": m.group(1) if m else "",
                "tribunal": tribunal, "date": d.isoformat(), "resume": cut(desc, 600),
                "url": text(it, "link"), "source": "CanLII",
            })
    return out


def from_scc():
    out = []
    try:
        its = items_of(fetch("https://decisions.scc-csc.ca/scc-csc/scc-csc/fr/rss.do"))
    except Exception as e:  # noqa: BLE001
        log("CSC échec:", e)
        return out
    for it in its:
        title, desc = clean(text(it, "title")), clean(text(it, "description"))
        m = re.search(r"publié le (\d{4}-\d{2}-\d{2})", desc)
        if not m:
            continue  # ignore les simples mises à jour
        d = dt.date.fromisoformat(m.group(1))
        if not recent(d):
            continue
        if not (re.search(r"criminel|Charte", desc, re.I) or CRIM_TITLE.search(title)):
            continue
        ref = re.search(r"(\d{4} CSC \d+)", title)
        name = re.split(r"\s+-\s+\d{4} CSC", title)[0].strip()
        domaine = re.sub(r"\s*—?\s*(Nouveau document publié|Document mis-à-jour).*$", "", desc).strip(" —")
        out.append({
            "col": "decisions", "titre": name, "reference": ref.group(1) if ref else "",
            "tribunal": "Cour suprême du Canada", "date": d.isoformat(),
            "resume": domaine, "url": text(it, "link"), "source": "Cour suprême du Canada",
        })
    return out


def from_legisinfo():
    out = []
    try:
        its = items_of(fetch("https://www.parl.ca/legisinfo/fr/projets-de-loi/rss"))
    except Exception as e:  # noqa: BLE001
        log("LEGISinfo échec:", e)
        return out
    for it in its:
        title, desc = clean(text(it, "title")), clean(text(it, "description"))
        d = pub_date(text(it, "pubDate"))
        if not recent(d) or not LEGIS_KW.search(title):
            continue
        out.append({
            "col": "juridique", "categorie": "Législation", "titre": title, "date": d.isoformat(),
            "resume": desc, "url": text(it, "link"), "source": "Parlement du Canada (LEGISinfo)",
            "key": title + "|" + desc,  # une nouvelle étape = un nouvel élément
        })
    return out


def from_pro_feeds():
    out = []
    for url, source in [("https://droit-inc.com/rss", "Droit-inc"), ("https://www.cba.org/rss", "Association du Barreau canadien")]:
        try:
            its = items_of(fetch(url))
        except Exception as e:  # noqa: BLE001
            log(source, "échec:", e)
            continue
        for it in its:
            title, desc = clean(text(it, "title")), clean(text(it, "description"))
            d = pub_date(text(it, "pubDate"))
            if not recent(d):
                continue
            kw = PRO_KW if source == "Droit-inc" else re.compile(r"criminal|crimin|sentenc|bail|youth justice|Criminal Code|prison|policing|C-\d+", re.I)
            if not kw.search(title + " " + desc):
                continue
            out.append({
                "col": "juridique", "categorie": "Barreau et associations", "titre": title, "date": d.isoformat(),
                "resume": cut(desc), "url": text(it, "link"), "source": source,
            })
    return out


NEWS_SOURCES = re.compile(
    r"Radio-Canada|ICI |La Presse|Le Devoir|Journal de Montréal|Journal de Québec|TVA|Noovo|QUB|98\.5|Cogeco|"
    r"Le Soleil|La Tribune|Le Nouvelliste|Le Droit|La Voix de l.Est|Le Quotidien|Les Coops de l.information|"
    r"CBC|Gazette|CTV|Global News|Globe and Mail|National Post|Toronto Star|Canadian Press|La Presse canadienne|"
    r"Droit-inc|L.actualité|Métro|Info-web|Les Affaires|Narcity|Le Courrier|L.Écho|Néomédia|InfoSuroit|EST MEDIA|"
    r"MonTerrebonne|MaTv|CHOI|FM93|Rouge FM|NRJ|Énergie|BLVD|Cool FM|O103|KYK|CKOI|"
    r"SPVM|Sûreté du Québec|Barreau du Québec|\bJournal Le\b|Le Reflet|Courrier|Citoyen|\bMon [A-ZÉ]|\bFM \d|Zone911|"
    r"Le Peuple|L.Avant-Poste|Le Progrès|L.Express|Le Canada Français|InfoDimanche|Le Guide|Le Charlevoisien|L.Hebdo", re.I)
NEWS_TITLE = re.compile(
    r"polic|policier|SPVM|\bSQ\b|Sûreté|GRC|\bBEI\b|UPAC|DPCP|accus|arrest|arrêté|procès|juge|jur[yé]|tribunal|cour\b|"
    r"palais de justice|coupable|acquitt|peine|prison|pénitenci|détenu|détention|libération|caution|enquête|"
    r"meurtre|homicide|crime|criminel|agression|violence|vol\b|fraude|drogue|stupéfiant|arme|fusillade|"
    r"victime|plainte|poursuite|Code criminel|LSJPA|Jordan|aide juridique|avocat|"
    r"amende|constat|infraction|contravention|pénal|cour municipale", re.I)


def relevant_news(title, source):
    return bool(NEWS_SOURCES.search(source or "") and NEWS_TITLE.search(title or ""))


def from_news():
    out = []
    for cat, queries in NEWS.items():
        for q in queries:
            if os.environ.get("SKIP_NEWS"):
                break
            url = "https://news.google.com/rss/search?" + urllib.parse.urlencode(
                {"q": q + " when:3d", "hl": "fr-CA", "gl": "CA", "ceid": "CA:fr"})
            try:
                its = items_of(fetch(url))
            except Exception as e:  # noqa: BLE001
                log("Actualités", q, "échec:", e)
                continue
            for it in its[:8]:
                title = clean(text(it, "title"))
                d = pub_date(text(it, "pubDate"))
                if not recent(d):
                    continue
                src = clean(text(it, "source"))
                if src and title.endswith(" - " + src):
                    title = title[: -len(src) - 3]
                if not relevant_news(title, src):
                    continue
                out.append({
                    "col": "presse", "categorie": cat, "titre": title, "date": d.isoformat(),
                    "resume": "", "url": text(it, "link"), "source": src or "Google Actualités",
                    "key": re.sub(r"\W+", " ", title.lower())[:90],
                })
    return out


# ---------- Fusion ----------

def ident(item):
    return item.pop("key", None) or item.get("reference") or item["url"]


PENAL_RE = re.compile(
    r"Code de procédure pénale|\bC\.\s?p\.\s?p\.|Code de la sécurité routière|\bC\.\s?s\.\s?r\.|constat d.infraction|"
    r"infraction pénale|poursuite pénale|infractions? réglementaires?|amende|contravention|Règlement municipal|stationnement|"
    r"Loi sur la santé et la sécurité du travail|Loi sur la qualité de l.environnement|Loi sur les impôts|Loi sur l.administration fiscale|"
    r"Loi sur la protection du consommateur|Loi sur les valeurs mobilières|Loi sur les produits alimentaires|Loi sur la santé publique|"
    r"Ville de |Municipalité de |Agence du revenu du Québec c\.|Commission des normes|Autorité des marchés financiers c\.|MAPAQ|CNESST",
    re.I)
CRIMINAL_RE = re.compile(r"Code criminel|\bC\.\s?cr\.|(^|\s)R\. c\.|c\. R\.|LSJPA|Loi réglementant certaines drogues|criminel", re.I)


def domaine(item):
    """« criminel » ou « penal » : sert aux onglets du site."""
    if item.get("domaine_ia") in ("criminel", "penal"):
        return item["domaine_ia"]
    if item["col"] == "presse":
        return "penal" if item.get("categorie") == "Droit pénal et réglementaire" else "criminel"
    texte = " ".join(str(item.get(k, "")) for k in ("titre", "source_resume", "resume"))
    if item["col"] == "decisions":
        crim_titre = re.search(r"(^|\s)R\. c\.|c\. R\.|LSJPA", item.get("titre", ""))
        if PENAL_RE.search(texte) and not crim_titre and not re.search(r"Code criminel|\bC\.\s?cr\.", texte):
            return "penal"
        return "criminel"
    return "penal" if PENAL_RE.search(texte) and not CRIMINAL_RE.search(texte) else "criminel"


def main():
    try:
        with open(DATA, encoding="utf-8") as f:
            store = json.load(f)
    except FileNotFoundError:
        store = {"items": []}
    # applique les filtres actuels aux éléments déjà enregistrés
    store["items"] = [i for i in store["items"] if i["col"] != "presse" or relevant_news(i["titre"], i.get("source"))]
    known = {i["id"] for i in store["items"]}
    added = 0
    for item in from_canlii() + from_scc() + from_legisinfo() + from_pro_feeds() + from_news():
        iid = item["col"] + ":" + ident(item)
        if iid in known:
            continue
        item["id"] = iid
        item["trouve_le"] = TODAY.isoformat()
        store["items"].append(item)
        known.add(iid)
        added += 1
    cutoff = (TODAY - dt.timedelta(days=KEEP_DAYS)).isoformat()
    store["items"] = [i for i in store["items"] if i.get("trouve_le", "") >= cutoff]
    for i in store["items"]:
        i["domaine"] = domaine(i)
    store["items"].sort(key=lambda i: (i["trouve_le"], i.get("date", "")), reverse=True)
    if added or not os.path.exists(DATA):
        store["mis_a_jour"] = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    os.makedirs(os.path.dirname(DATA), exist_ok=True)
    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    log(f"{added} nouveaux éléments; total {len(store['items'])}")


if __name__ == "__main__":
    main()
