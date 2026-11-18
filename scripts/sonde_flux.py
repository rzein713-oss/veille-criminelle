"""Diagnostic temporaire : quels fils RSS de médias répondent et fournissent un résumé."""
import re, urllib.request, xml.etree.ElementTree as ET, html
UA = "Mozilla/5.0 (compatible; RevueCriminellePenaleQC/1.0; +https://subrosaconnect.ca)"
FEEDS = """https://www.lapresse.ca/actualites/justice-et-faits-divers/rss
https://www.lapresse.ca/actualites/rss
https://ici.radio-canada.ca/rss/4159
https://ici.radio-canada.ca/rss/1000524
https://ici.radio-canada.ca/rss/96
https://www.ledevoir.com/rss/manchettes.xml
https://www.ledevoir.com/rss/section/societe/justice.xml
https://www.tvanouvelles.ca/rss.xml
https://www.tvanouvelles.ca/actualites/justice-et-faits-divers/rss.xml
https://www.journaldemontreal.com/rss.xml
https://www.journaldemontreal.com/actualite/justice-et-faits-divers/rss.xml
https://www.journaldequebec.com/rss.xml
https://www.noovo.info/rss/
https://www.noovo.info/rss.xml
https://www.cbc.ca/webfeed/rss/rss-canada-montreal
https://montrealgazette.com/feed/
https://montrealgazette.com/category/news/crime/feed
https://globalnews.ca/montreal/feed/
https://www.lesoleil.com/arc/outboundfeeds/rss/
https://www.latribune.ca/arc/outboundfeeds/rss/
https://www.985fm.ca/rss/nouvelles
https://www.qub.ca/rss
https://saaq.gouv.qc.ca/rss/salle-de-presse""".split()
def get(u):
    with urllib.request.urlopen(urllib.request.Request(u, headers={"User-Agent": UA}), timeout=25) as r:
        return r.geturl(), r.read()
for u in FEEDS:
    try:
        _, b = get(u); its = list(ET.fromstring(b).iter("item"))
        d = re.sub(r"<[^>]+>", " ", html.unescape(its[0].findtext("description") or "")).strip() if its else ""
        print(f"OK {len(its):3d} items | desc {len(d):4d} | {u}\n      ex: {(its[0].findtext('title') or '')[:70]} || {d[:140]}")
    except Exception as e:
        print(f"ECHEC {u} : {e}")
# Google Actualités : peut-on atteindre l'article et sa description ?
_, b = get("https://news.google.com/rss/search?q=SPVM+when:2d&hl=fr-CA&gl=CA&ceid=CA:fr")
for it in list(ET.fromstring(b).iter("item"))[:2]:
    link = it.findtext("link")
    try:
        final, page = get(link); page = page.decode("utf-8", "replace")
        m = re.search(r'<meta[^>]+property="og:description"[^>]+content="([^"]*)"', page)
        print("GN", final[:90], "| og:", (m.group(1)[:120] if m else None))
    except Exception as e:
        print("GN échec", e)
