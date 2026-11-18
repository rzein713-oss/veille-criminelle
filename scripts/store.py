"""Stockage des éléments du site : un fichier par année (data/items-AAAA.json) et un index (data/index.json).

Rien n'est jamais supprimé : l'historique complet est conservé, réparti par année d'ajout,
pour que le site ne charge que les années dont il a besoin.
"""
import datetime as dt
import glob
import json
import os

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_DIR = os.path.join(ROOT, "data")
INDEX = os.path.join(DATA_DIR, "index.json")
LEGACY = os.path.join(DATA_DIR, "items.json")


def load():
    items, meta = [], {}
    for path in sorted(glob.glob(os.path.join(DATA_DIR, "items-*.json"))):
        with open(path, encoding="utf-8") as f:
            items += json.load(f).get("items", [])
    if os.path.exists(INDEX):
        with open(INDEX, encoding="utf-8") as f:
            meta = json.load(f)
    if os.path.exists(LEGACY):  # ancien format (un seul fichier) : fusionné puis retiré à la sauvegarde
        with open(LEGACY, encoding="utf-8") as f:
            old = json.load(f)
        known = {i["id"] for i in items}
        items += [i for i in old.get("items", []) if i["id"] not in known]
        meta.setdefault("mis_a_jour", old.get("mis_a_jour"))
    return {"items": items, "mis_a_jour": meta.get("mis_a_jour")}


def save(store, changed=True):
    os.makedirs(DATA_DIR, exist_ok=True)
    by_year = {}
    for i in store["items"]:
        by_year.setdefault((i.get("trouve_le") or "0000")[:4], []).append(i)
    for year, arr in by_year.items():
        arr.sort(key=lambda i: (i.get("trouve_le", ""), i.get("date", "")), reverse=True)
        with open(os.path.join(DATA_DIR, f"items-{year}.json"), "w", encoding="utf-8") as f:
            json.dump({"annee": year, "items": arr}, f, ensure_ascii=False, indent=1)
    mis_a_jour = store.get("mis_a_jour")
    if changed or not mis_a_jour:
        mis_a_jour = dt.datetime.now(dt.timezone.utc).isoformat(timespec="minutes")
    index = {
        "mis_a_jour": mis_a_jour,
        "total": len(store["items"]),
        "annees": [{"annee": y, "n": len(by_year[y]), "decisions": sum(1 for i in by_year[y] if i["col"] == "decisions")}
                   for y in sorted(by_year, reverse=True)],
    }
    with open(INDEX, "w", encoding="utf-8") as f:
        json.dump(index, f, ensure_ascii=False, indent=1)
    if os.path.exists(LEGACY):
        os.remove(LEGACY)
