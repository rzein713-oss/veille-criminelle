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
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as datastore  # noqa: E402  (un fichier par année, conservation à vie)
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
    ("csc", "Cour suprême du Canada"),  # flux CanLII : contient la classification (questions, résultat)
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
        '"palais de justice" Québec accusé', '"capacités affaiblies" OR "alcool au volant" OR "conduite dangereuse" Québec', '"reconnu coupable" Québec', 'procès meurtre Québec', '"Chambre de la jeunesse" OR LSJPA',
    ],
    "Tendances et société": [
        '"crime organisé" Québec', '"violence conjugale" tribunal Québec', '"aide juridique" Québec',
    ],
    "Sécurité routière et procédure pénale": [
        'photo radar Québec', '"points d\'inaptitude" OR "suspension de permis" SAAQ', 'SAAQ permis de conduire amende',
        '"Code de la sécurité routière" modification OR nouvelle règle', '"Code de la sécurité routière" cour OR tribunal',
        '"constat d\'infraction" Québec', '"Code de procédure pénale"', '"excès de vitesse" amende Québec',
        '"cellulaire au volant" OR "distraction au volant" Québec',
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


# ---------- Décomposition des classifications SOQUIJ ----------

RESULT_RE = re.compile(
    r"accueilli|rejet[ée]|ordonnée?|acquitt|coupable|confirmée?|infirmée?|modifiée?|fixée?s?\b|arrêt des procédures|"
    r"annulée?|cassée?|autorisée?|refusée?|accordée?|aucune violation|violation (retenue|reconnue)|exclusion|exclue?s?\b|"
    r"condamn|libération|sursis|irrecevable|accueillie|rejetée|maintenue?s?\b|réduite|substituée?|imposée?s?\b|suspendue?",
    re.I)
LAW_RE = re.compile(r"(^|\s)(Code|Loi|Règlement|Charte|C\.\s?cr\.|C\.\s?p\.\s?p\.|C\.\s?s\.\s?r\.|L\.R\.|art\.)", re.I)
CASE_RE = re.compile(r"\bc\.\s|R\. c\.|citée?s?$", re.I)
HEADINGS = {
    "infractions criminelles et réglementaires", "procédure", "peine", "sentence", "appel", "constitution", "droits garantis",
    "preuve", "droit administratif", "détermination de la peine", "procédure pénale", "procédure criminelle", "droit criminel",
}


def decompose(classification):
    """Sépare une classification SOQUIJ en questions, résumé, résultat et dispositions."""
    questions, resultat, resume, lois = [], [], [], []
    for seg in re.split(r"\s+—\s+", classification or ""):
        seg = seg.strip(" .")
        if not seg or seg.endswith("…"):
            continue
        if "?" in seg:
            questions.append(seg.replace(" ?", "?"))
        elif LAW_RE.match(seg) and len(seg) < 90:
            lois.append(seg)
        elif RESULT_RE.search(seg) and len(seg) < 90 and not re.match(r"(Requêtes?|Demandes?) modifiées?", seg):
            resultat.append(seg)
        elif seg.lower() in HEADINGS or CASE_RE.search(seg) or len(seg.split()) < 3:
            continue
        else:
            resume.append(seg)
    uniq = lambda xs: list(dict.fromkeys(xs))
    return {
        "questions": " ".join(uniq(questions)),
        "resultat": "; ".join(uniq(resultat)),
        "resume": ". ".join(uniq(resume)) + ("." if resume else ""),
        "dispositions": "; ".join(uniq(lois)),
    }


# ---------- Sources ----------

def from_canlii():
    out = []
    for db, court in CANLII:
        try:
            juri = "ca" if db == "csc" else "qc"
            its = items_of(fetch(f"https://www.canlii.org/fr/{juri}/{db}/rss_new.xml"))
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
            m = re.search(r"(\d{4} (?:QC[A-Z]+|CSC) \d+)", title)
            name = re.sub(r",?\s*\d{4} (?:QC[A-Z]+|CSC) \d+.*$", "", title).strip()
            out.append({
                "col": "decisions", "titre": name or title, "reference": m.group(1) if m else "",
                "tribunal": tribunal, "date": d.isoformat(), "resume": cut(desc, 1500),
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


ASSNAT_KW = re.compile(
    r"Code de la sécurité routière|Code de procédure pénale|sécurité routière|Société de l.assurance automobile|pénal|criminel|"
    r"sécurité publique|police|policier|victime|services correctionnels|détention|carcéral|système de justice|poursuites|"
    r"cour municipale|violence|armes? à feu|drogue|cannabis|alcool au volant|exploitation sexuelle|crime",
    re.I)
ASSNAT_STATE = os.path.join(ROOT, "data", "assnat.json")


def assnat_session_page():
    for leg in range(46, 42, -1):
        for ses in range(5, 0, -1):
            url = f"https://www.assnat.qc.ca/fr/travaux-parlementaires/projets-loi/projets-loi-{leg}-{ses}.html"
            try:
                return url, fetch(url, tries=1).decode("utf-8", "replace")
            except Exception:  # noqa: BLE001
                continue
    return None, None


def from_assnat():
    """Projets de loi du Québec : un élément quand un projet pertinent est déposé ou franchit une étape."""
    out = []
    url, page = assnat_session_page()
    if not page:
        log("Assemblée nationale : page introuvable")
        return out
    try:
        with open(ASSNAT_STATE, encoding="utf-8") as f:
            state = json.load(f)
    except FileNotFoundError:
        state = {}
    for row in re.findall(r"<tr>(.*?)</tr>", page, re.S):
        tds = [re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", t))).strip() for t in re.findall(r"<td[^>]*>(.*?)</td>", row, re.S)]
        if len(tds) < 4 or not tds[0].isdigit():
            continue
        num, stage, kind = tds[0], tds[3], tds[2]
        m = re.search(r"<span[^>]*display:none[^>]*>(.*?)</span>", row, re.S)
        titre = html.unescape(m.group(1)).strip() if m else tds[1]
        if not ASSNAT_KW.search(titre):
            continue
        lien = re.search(r"href='(/fr/travaux-parlementaires/projets-loi/projet-loi-[^']+)'", row)
        if state.get(num) == stage:
            continue
        state[num] = stage
        out.append({
            "col": "juridique", "categorie": "Législation", "titre": f"Projet de loi n° {num} — {titre}",
            "date": TODAY.isoformat(), "resume": f"Assemblée nationale du Québec · dernière étape franchie : {stage} · {kind}.",
            "url": "https://www.assnat.qc.ca" + lien.group(1) if lien else url,
            "source": "Assemblée nationale du Québec", "key": f"assnat:{url[-9:-5]}:{num}:{stage}",
        })
    with open(ASSNAT_STATE, "w", encoding="utf-8") as f:
        json.dump(state, f, ensure_ascii=False, indent=1, sort_keys=True)
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


# « Pénal » = Code de procédure pénale et Code de la sécurité routière (SAAQ, points d'inaptitude, etc.) seulement.
PENAL_RE = re.compile(
    r"Code de procédure pénale|\bC\.\s?p\.\s?p\.|Code de la sécurité routière|\bC\.\s?s\.\s?r\.|sécurité routière|"
    r"SAAQ|Société de l.assurance automobile|points? d.inaptitude|constat d.infraction|photo.?radar|cinémomètre|"
    r"permis de conduire|excès de vitesse|distractions? au volant|cellulaire au volant|Règlement sur les distractions",
    re.I)
CRIMINAL_RE = re.compile(
    r"Code criminel|\bC\.\s?cr\.|(^|\s)R\. c\.|c\. R\.|LSJPA|justice pénale pour les adolescents|"
    r"Loi réglementant certaines drogues|\bLRCDAS\b|criminel|crime", re.I)
PENAL_NEWS_CAT = "Sécurité routière et procédure pénale"


ROUTE_RE = re.compile(
    r"sécurité routière|\bC\.\s?s\.\s?r\.|capacités affaiblies|alcool au volant|conduite (dangereuse|avec|automobile|d.un véhicule)|"
    r"\bvolant\b|délit de fuite|véhicule routier|assurance automobile|routière|routier|radar|excès de vitesse|permis de conduire|points d.inaptitude|SAAQ|"
    r"distraction|cellulaire au volant|camionneur|piéton|cycliste|accident de la route|art\. 320\.1\d",
    re.I)


def domaine(item):
    """« criminel », « penal » ou None (hors champ : retiré du site)."""
    if item.get("domaine_ia") in ("criminel", "penal"):
        return item["domaine_ia"]
    titre = item.get("titre", "")
    texte = " ".join(str(item.get(k, "")) for k in ("titre", "source_resume", "resume", "dispositions"))
    if item["col"] == "presse":
        if item.get("categorie") in (PENAL_NEWS_CAT, "Droit pénal et réglementaire"):
            return "penal" if PENAL_RE.search(texte) else None
        return "criminel"
    if item["col"] == "decisions":
        if re.search(r"(^|\s)R\. c\.|c\. R\.|LSJPA|c\. Sa Majesté", titre) or re.search(r"Code criminel|\bC\.\s?cr\.|LSJPA|drogues", texte):
            return "criminel"
        if PENAL_RE.search(texte):
            return "penal"
        return None  # autres infractions réglementaires : hors champ
    # législation et profession
    if PENAL_RE.search(texte) and not re.search(r"Code criminel", texte):
        return "penal"
    if CRIMINAL_RE.search(texte) or item.get("categorie") == "Barreau et associations":
        return "criminel"
    return None


def main():
    store = datastore.load()
    # applique les filtres actuels aux éléments déjà enregistrés
    store["items"] = [i for i in store["items"] if i["col"] != "presse" or relevant_news(i["titre"], i.get("source"))]
    known = {i["id"] for i in store["items"]}
    added = 0
    # Cour suprême : remplacée par le flux CanLII (plus complet) — retire les anciennes fiches du site de la CSC
    store["items"] = [i for i in store["items"] if not (i["col"] == "decisions" and i.get("source") == "Cour suprême du Canada")]
    known = {i["id"] for i in store["items"]}
    for item in from_canlii() + from_legisinfo() + from_assnat() + from_pro_feeds() + from_news():
        iid = item["col"] + ":" + ident(item)
        if iid in known:
            continue
        item["id"] = iid
        item["trouve_le"] = TODAY.isoformat()
        store["items"].append(item)
        known.add(iid)
        added += 1
    for i in store["items"]:
        if i["col"] == "decisions" and not i.get("ia") and i.get("source") == "CanLII":
            i.setdefault("source_resume", i.get("resume", ""))
            i.update(decompose(i["source_resume"]))
        i["domaine"] = domaine(i)
    store["items"] = [i for i in store["items"] if i["domaine"]]
    for i in store["items"]:
        i["route"] = bool(ROUTE_RE.search(" ".join(str(i.get(k, "")) for k in ("titre", "resume", "source_resume", "questions", "dispositions"))))
    store["items"].sort(key=lambda i: (i["trouve_le"], i.get("date", "")), reverse=True)
    datastore.save(store, changed=bool(added))
    log(f"{added} nouveaux éléments; total {len(store['items'])}")


if __name__ == "__main__":
    main()
