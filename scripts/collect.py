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
CRIM_TITLE = re.compile(r"(^|\s)R\. c\.|c\. R\.\s*$|LSJPA|Directeur des poursuites criminelles|\bDPCP\b|c\. Sa Majesté", re.I)
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
CASE_RE = re.compile(r"\bc\.\s|\bv\.\s|R\. c\.|citée?s?$|\b(19|20)\d\d (QC|NL|ON|BC|AB|CS|SC|NS|NB|MB|SK)[A-Z]* \d+", re.I)
HEADINGS = {
    "infractions criminelles et réglementaires", "procédure", "peine", "sentence", "appel", "constitution", "droits garantis",
    "preuve", "droit administratif", "détermination de la peine", "procédure pénale", "procédure criminelle", "droit criminel",
}


def decompose(classification):
    """Sépare une classification SOQUIJ en questions, résumé, résultat et dispositions."""
    questions, resultat, resume, lois = [], [], [], []
    for seg in re.split(r"\s+[—|]\s+", classification or ""):
        seg = seg.strip(" .")
        if not seg or seg.endswith("…"):
            continue
        if "?" in seg:
            questions.append(seg.replace(" ?", "?"))
            continue
        if LAW_RE.match(seg) and len(seg) < 90:
            lois.append(seg)
            continue
        if seg.lower() in HEADINGS:
            continue
        parts = [p.strip(" .") for p in seg.split(", ")]
        res = [p for p in parts if RESULT_RE.search(p) and len(p) < 90 and not CASE_RE.search(p)
               and not re.match(r"(Requêtes?|Demandes?) modifiées?", p)]
        if res and len(seg) < 140:
            resultat += res
        elif CASE_RE.search(seg) or len(seg.split()) < 3:
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


API_DBS = [
    ("qccq", "Cour du Québec – chambre criminelle et pénale"),
    ("qccs", "Cour supérieure"),
    ("qccm", "Cour municipale"),
    ("qcca", "Cour d'appel du Québec"),
]
API_TITLE = re.compile(
    r"(^|\s)R\. c\.|c\. R\.\s*$|LSJPA|Directeur des poursuites criminelles|Sa Majesté|"
    r"^(Ville|Municipalité|Cité|Village|Paroisse|Procureur général du Québec|Agence du revenu du Québec|Société de l.assurance automobile)\b.* c\.",
    re.I)


def from_canlii_api(known_refs):
    """API officielle de CanLII (métadonnées seulement) : toutes les décisions publiées récemment.

    Limites de CanLII : 5 000 requêtes/jour, 2 requêtes/seconde, une à la fois — on attend 0,6 s entre chaque appel.
    """
    key = os.environ.get("CANLII_API_KEY")
    if not key:
        return []
    days = int(os.environ.get("CANLII_DAYS", "4"))
    after = (TODAY - dt.timedelta(days=days)).isoformat()
    out = []

    def api(path, **params):
        time.sleep(0.6)
        q = urllib.parse.urlencode({**params, "api_key": key})
        return json.loads(fetch(f"https://api.canlii.org/v1/caseBrowse/fr/{path}?{q}"))

    for db, court in API_DBS:
        try:
            cases = api(f"{db}/", offset=0, resultCount=1000, publishedAfter=after).get("cases", [])
        except Exception as e:  # noqa: BLE001
            log("API CanLII", db, "échec:", type(e).__name__)
            continue
        for c in cases:
            title = c.get("title", "")
            ref = re.sub(r"\s*\(CanLII\)\s*$", "", c.get("citation", ""))
            if not API_TITLE.search(title) or ref in known_refs:
                continue
            cid = c.get("caseId")
            case_id = (cid.get("fr") or next(iter(cid.values()), "")) if isinstance(cid, dict) else cid
            if not case_id:
                continue
            try:
                meta = api(f"{db}/{case_id}/")
            except Exception as e:  # noqa: BLE001
                log("API CanLII métadonnées", ref, "échec:", type(e).__name__)
                continue
            classification = clean(meta.get("keywords", ""))
            tribunal = "Chambre de la jeunesse" if db == "qccq" and re.search(r"LSJPA|adolescent", title + classification, re.I) else court
            out.append({
                "col": "decisions", "titre": title, "reference": ref, "tribunal": tribunal,
                "date": meta.get("decisionDate", ""), "resume": cut(classification, 1500),
                "url": meta.get("longUrl") or c.get("longUrl", ""), "source": "CanLII",
            })
            known_refs.add(ref)
    log(f"API CanLII : {len(out)} décisions criminelles ou pénales ajoutées")
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
        lien = text(it, "link")
        m = re.search(r"/(?:projet-de-loi|bill)/(\d+-\d+)/([a-z]-\d+)", lien, re.I)
        doc = f"https://www.parl.ca/DocumentViewer/fr/{m.group(1)}/projet-loi/{m.group(2).upper()}/premiere-lecture" if m else ""
        if m:
            lien = f"https://www.parl.ca/legisinfo/fr/projet-de-loi/{m.group(1)}/{m.group(2).lower()}"
        out.append({
            "col": "juridique", "categorie": "Législation", "titre": title, "date": d.isoformat(),
            "resume": "", "etape": desc.replace("Dernière activité: ", ""), "url": lien, "doc": doc,
            "source": "Parlement du Canada (LEGISinfo)",
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
        pdf = re.search(r"href='(https://www\.assnat\.qc\.ca/Media/Process\.aspx[^']+)'", row)
        if state.get(num) == stage:
            continue
        state[num] = stage
        out.append({
            "col": "juridique", "categorie": "Législation", "titre": f"Projet de loi n° {num} — {titre}",
            "date": TODAY.isoformat(), "resume": "", "etape": f"{stage} · {kind}",
            "doc": html.unescape(pdf.group(1)) if pdf else "",
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
    r"meurtre|homicide|tuée?s?\b|crime|criminel|agression|violence|vol\b|vandalis|fraude|drogue|stupéfiant|arme|fusillade|"
    r"victime|plainte|poursuite|Code criminel|LSJPA|Jordan|aide juridique|avocat|"
    r"amende|constat|infraction|contravention|pénal|cour municipale", re.I)


def relevant_news(title, source, resume=""):
    texte = (title or "") + " " + (resume or "")
    return bool(NEWS_SOURCES.search(source or "") and (NEWS_TITLE.search(texte) or NEWS_STRONG.search(texte)))


MEDIA_FEEDS = [
    ("https://www.lapresse.ca/actualites/justice-et-faits-divers/rss", "La Presse", True),
    ("https://www.lapresse.ca/actualites/rss", "La Presse", False),
    ("https://ici.radio-canada.ca/rss/4159", "Radio-Canada", False),
    ("https://ici.radio-canada.ca/rss/1000524", "Radio-Canada", False),
    ("https://ici.radio-canada.ca/rss/96", "Radio-Canada", False),
    ("https://www.ledevoir.com/rss/manchettes.xml", "Le Devoir", False),
    ("https://www.journaldemontreal.com/rss.xml", "Journal de Montréal", False),
    ("https://www.journaldequebec.com/rss.xml", "Journal de Québec", False),
    ("https://globalnews.ca/montreal/feed/", "Global News", False),
]
NEWS_STRONG = re.compile(
    r"accusée?s?\b|procès|coupable|acquitt|meurtre|homicide|agression|arrestation|arrêtée?s?\b|policier|SPVM|SPVQ|"
    r"Sûreté du Québec|\bSQ\b|\bGRC\b|\bBEI\b|UPAC|DPCP|palais de justice|détenus?\b|prison|pénitencier|libération conditionnelle|"
    r"Code criminel|LSJPA|crime organisé|fusillade|constat d.infraction|\bSAAQ\b|photo.?radar|points d.inaptitude|"
    r"Code de la sécurité routière|capacités affaiblies|alcool au volant|délit de fuite|charged|trial|police|sentenced|guilty",
    re.I)
NEWS_CATS = [
    (PENAL_NEWS_CAT_RE := re.compile(r"\bSAAQ\b|photo.?radar|cinémomètre|points d.inaptitude|constat d.infraction|excès de vitesse|"
                                      r"Code de la sécurité routière|permis de conduire|cellulaire au volant|distraction au volant|"
                                      r"Code de procédure pénale", re.I), "Sécurité routière et procédure pénale"),
    (re.compile(r"procès|meurtre|homicide|tuée?s?\b|poignard|accusée?s?\b|coupable|acquitt|peine de|condamn|sentence|palais de justice|juge|jury|plaidoyer|trial|guilty|sentenced", re.I), "Crimes et procès"),
    (re.compile(r"prison|pénitencier|détenu|détention|carcéral|libération conditionnelle|Service correctionnel|Bordeaux|établissement de détention", re.I), "Système carcéral"),
    (re.compile(r"polic|SPVM|SPVQ|Sûreté du Québec|\bSQ\b|\bGRC\b|\bBEI\b|UPAC|enquête|perquisition|arrestation|arrêté", re.I), "Police et enquêtes"),
    (re.compile(r"ministre|projet de loi|gouvernement|Code criminel|réforme|Assemblée nationale|Parlement|Ottawa", re.I), "Politique et justice"),
]


CIVIL_RE = re.compile(r"poursuivie?s? pour [\d  ]+|action collective|recours collectif|poursuite civile|dommages-intérêts", re.I)


def news_category(text_):
    for rx, cat in NEWS_CATS:
        if rx.search(text_):
            return cat
    return "Tendances et société"


def from_news():
    """Revue de presse : fils RSS des médias (chaque article arrive avec son résumé)."""
    out = []
    if os.environ.get("SKIP_NEWS"):
        return out
    for url, source, justice_feed in MEDIA_FEEDS:
        try:
            its = items_of(fetch(url))
        except Exception as e:  # noqa: BLE001
            log("Média", source, "échec:", e)
            continue
        for it in its:
            title, desc = clean(text(it, "title")), clean(text(it, "description"))
            d = pub_date(text(it, "pubDate"))
            if not recent(d) or not desc:
                continue
            if not (justice_feed or NEWS_STRONG.search(title) or (NEWS_TITLE.search(title) and NEWS_STRONG.search(desc))):
                continue
            if CIVIL_RE.search(title + " " + desc) and not NEWS_STRONG.search(title):
                continue
            out.append({
                "col": "presse", "categorie": news_category(title + " " + desc), "titre": title, "date": d.isoformat(),
                "resume": cut(desc, 600), "url": text(it, "link"), "source": source,
                "key": re.sub(r"\W+", " ", title.lower())[:90],
            })
    return out


# ---------- Sommaires des projets de loi ----------

def sommaire_federal(url):
    page = fetch(url).decode("utf-8", "replace")
    m = re.search(r"<h2[^>]*>\s*SOMMAIRE\s*</h2>(.*?)<h2", page, re.S)
    return cut(clean(m.group(1)), 900) if m else ""


def sommaire_quebec(url):
    from io import BytesIO
    from pypdf import PdfReader  # installé par le flux de travail
    reader = PdfReader(BytesIO(fetch(url)))
    t = re.sub(r"\s+", " ", " ".join((p.extract_text() or "") for p in reader.pages[:3]))
    k = t.upper().find("NOTES EXPLICATIVES")
    if k < 0:
        return ""
    t = t[k + len("NOTES EXPLICATIVES"):]
    t = re.split(r"LOIS? MODIFIÉES? PAR|LOIS? ÉDICTÉES? PAR|RÈGLEMENTS? MODIFIÉS? PAR|Projet de loi n", t)[0]
    return cut(t.strip(" :–-"), 900)


def enrich_bills(items, limit=20):
    """Ajoute le sommaire officiel aux projets de loi qui n'en ont pas encore (quelques essais au plus)."""
    done = 0
    for i in items:
        if done >= limit or i.get("col") != "juridique" or i.get("resume") or not i.get("doc") or i.get("essais", 0) >= 3:
            continue
        i["essais"] = i.get("essais", 0) + 1
        try:
            txt = sommaire_quebec(i["doc"]) if "assnat" in i["doc"] else sommaire_federal(i["doc"])
        except Exception as e:  # noqa: BLE001
            log("Sommaire échec:", i["titre"][:60], e)
            continue
        if txt:
            i["resume"] = txt
            i.pop("essais", None)
        done += 1


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
    r"Code criminel|\bC\.\s?cr\.|(^|\s)R\. c\.|c\. R\.\s*$|LSJPA|justice pénale pour les adolescents|"
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
        if re.search(r"(^|\s)R\. c\.|c\. R\.\s*$|LSJPA|c\. Sa Majesté", titre) or re.search(r"Code criminel|\bC\.\s?cr\.|LSJPA|drogues", texte):
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
    store["items"] = [i for i in store["items"] if i["col"] != "presse" or relevant_news(i["titre"], i.get("source"), i.get("resume", ""))]
    known = {i["id"] for i in store["items"]}
    added = 0
    # Cour suprême : remplacée par le flux CanLII (plus complet) — retire les anciennes fiches du site de la CSC
    store["items"] = [i for i in store["items"] if not (i["col"] == "decisions" and i.get("source") == "Cour suprême du Canada")]
    known = {i["id"] for i in store["items"]}
    rss = from_canlii()
    refs = {i.get("reference") for i in store["items"] if i.get("reference")} | {i.get("reference") for i in rss if i.get("reference")}
    for item in rss + from_canlii_api(refs) + from_legisinfo() + from_assnat() + from_pro_feeds() + from_news():
        iid = item["col"] + ":" + ident(item)
        if iid in known:
            continue
        item["id"] = iid
        item["trouve_le"] = TODAY.isoformat()
        store["items"].append(item)
        known.add(iid)
        added += 1
    for i in store["items"]:
        if i["col"] == "juridique" and i.get("source") == "Parlement du Canada (LEGISinfo)" and not i.get("doc"):
            m = re.search(r"/(?:projet-de-loi|bill)/(\d+-\d+)/([a-z]-\d+)", i.get("url", ""), re.I)
            if m:
                i["doc"] = f"https://www.parl.ca/DocumentViewer/fr/{m.group(1)}/projet-loi/{m.group(2).upper()}/premiere-lecture"
                i["etape"], i["resume"] = i.get("resume", "").replace("Dernière activité: ", ""), ""
                i["url"] = f"https://www.parl.ca/legisinfo/fr/projet-de-loi/{m.group(1)}/{m.group(2).lower()}"
        if i["col"] == "juridique" and i.get("source") == "Assemblée nationale du Québec" and "dernière étape franchie" in i.get("resume", ""):
            i["etape"] = i["resume"].split("dernière étape franchie : ")[-1].rstrip(".")
            i["resume"] = ""
    enrich_bills(store["items"])
    for i in store["items"]:
        if i["col"] == "presse" and i.get("categorie") != "Sécurité routière et procédure pénale":
            i["categorie"] = news_category(i["titre"] + " " + i.get("resume", ""))
    store["items"] = [i for i in store["items"] if i["col"] != "presse" or not CIVIL_RE.search(i["titre"] + " " + i.get("resume", "")) or NEWS_STRONG.search(i["titre"])]
    # chaque article de la revue de presse doit avoir un résumé
    store["items"] = [i for i in store["items"] if i["col"] != "presse" or i.get("resume")]
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
