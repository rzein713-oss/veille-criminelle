"""Diagnostic temporaire : sources pour la revue de presse pénale (C.s.r., C.p.p.)."""
import re, urllib.request, urllib.parse, xml.etree.ElementTree as ET, html
UA = "Mozilla/5.0 (compatible; RevueCriminellePenaleQC/1.0; +https://subrosaconnect.ca)"
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25) as r:
        return r.read()
def show(u, n=3):
    try:
        its = list(ET.fromstring(get(u)).iter("item"))
        print(f"OK {len(its):3d} | {u}")
        for it in its[:n]:
            d = re.sub(r"<[^>]+>", " ", html.unescape(it.findtext("description") or "")).strip()
            print(f"    - {(it.findtext('title') or '')[:80]} || {d[:120]} || {(it.findtext('link') or '')[:100]}")
    except Exception as e:
        print(f"ECHEC {u} : {e}")
for q in ['SAAQ', '"photo radar" OR cinémomètre Québec', '"points d\'inaptitude"', '"Code de la sécurité routière"', '"constat d\'infraction" Québec', 'excès de vitesse amende Québec']:
    show("https://www.bing.com/news/search?" + urllib.parse.urlencode({"q": q, "format": "rss", "setlang": "fr-CA", "cc": "CA"}))
for u in ["https://saaq.gouv.qc.ca/salle-de-presse/communiques/rss", "https://saaq.gouv.qc.ca/feed", "https://saaq.gouv.qc.ca/rss",
          "https://www.sq.gouv.qc.ca/feed/", "https://www.sq.gouv.qc.ca/salle-de-presse/feed/", "https://www.quebec.ca/nouvelles/rss",
          "https://www.quebec.ca/rss/nouvelles", "https://www.caaquebec.com/fr/rss/", "https://www.guideautoweb.com/rss/"]:
    show(u, 2)
