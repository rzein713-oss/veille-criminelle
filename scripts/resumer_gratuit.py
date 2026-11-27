#!/usr/bin/env python3
"""Résumés clairs des décisions avec Google Gemini (palier gratuit).

La clé est lue dans GEMINI_API_KEY (secret GitHub), jamais dans le code. Sans clé, si le service
est indisponible ou si la limite quotidienne gratuite est atteinte, le site garde le résumé
généré automatiquement à partir de la classification (aucune IA).
"""
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import store as datastore  # noqa: E402

API = "https://generativelanguage.googleapis.com/v1beta"
MAX = int(os.environ.get("MAX_RESUMES", "40"))
PAUSE = float(os.environ.get("PAUSE_RESUMES", "7"))  # palier gratuit : quelques requêtes par minute

CONSIGNE = """Tu rédiges, en français juridique québécois clair, le résumé d'une décision pour des avocats en droit criminel et pénal.
On te donne l'intitulé, le tribunal et la classification SOQUIJ/CanLII (mots-clés séparés par « — » ou « | »).
Réponds UNIQUEMENT en JSON : {"resume": "...", "questions": "...", "resultat": "..."}
- resume : 2 ou 3 phrases complètes et fluides expliquant de quoi il s'agit et ce que le tribunal a décidé.
- questions : la ou les questions en litige, en phrase(s) interrogative(s) claire(s).
- resultat : l'issue en une phrase courte.
Règles : n'utilise que l'information fournie; n'invente aucun fait, nom, article ou résultat; si un élément manque, dis-le sobrement.
Ne nomme jamais un adolescent ou une victime mineure (LSJPA). Si la classification est en anglais, rédige quand même en français."""


def request(url, key, body=None):
    req = urllib.request.Request(url, data=json.dumps(body).encode() if body else None,
                                 method="POST" if body else "GET",
                                 headers={"x-goog-api-key": key, "Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=90) as r:
        return json.loads(r.read())


def pick_model(key):
    """Choisit le modèle « flash » le plus récent offert à cette clé (rapide et inclus dans le palier gratuit)."""
    preferred = os.environ.get("MODELE_GEMINI")
    if preferred:
        return preferred
    names = []
    url = f"{API}/models?pageSize=200"
    data = request(url, key)
    for m in data.get("models", []):
        name = m.get("name", "").split("/")[-1]
        if "generateContent" in m.get("supportedGenerationMethods", []) and "flash" in name \
                and not re.search(r"lite|image|tts|audio|live|thinking|exp|preview", name):
            names.append(name)

    def version(n):
        v = re.search(r"gemini-(\d+(?:\.\d+)?)", n)
        return float(v.group(1)) if v else 0.0
    names.sort(key=lambda n: (version(n), "latest" not in n), reverse=True)
    return names[0] if names else "gemini-flash-latest"


def summarize(model, item, key):
    body = {
        "systemInstruction": {"parts": [{"text": CONSIGNE}]},
        "contents": [{"role": "user", "parts": [{"text":
            f"Intitulé : {item['titre']}\nRéférence : {item.get('reference', '')}\n"
            f"Tribunal : {item.get('tribunal', '')}\nClassification : {item.get('source_resume', '')}"}]}],
        "generationConfig": {"temperature": 0.2, "responseMimeType": "application/json"},
    }
    out = request(f"{API}/models/{model}:generateContent", key, body)
    text = "".join(p.get("text", "") for p in out["candidates"][0]["content"]["parts"])
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text.strip())
    return json.loads(text)


def main():
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        print("Pas de clé GEMINI_API_KEY : résumé automatique sans IA conservé.", file=sys.stderr)
        return
    store = datastore.load()
    todo = [i for i in store["items"] if i["col"] == "decisions" and not i.get("ia") and not i.get("ia_libre") and i.get("source_resume")]
    todo.sort(key=lambda i: i.get("trouve_le", ""), reverse=True)
    if not todo:
        print("Aucune décision à résumer.", file=sys.stderr)
        return
    try:
        model = pick_model(key)
    except urllib.error.HTTPError as e:
        print(f"Gemini indisponible ({e.code}) : {e.read()[:200]!r}", file=sys.stderr)
        return
    except urllib.error.URLError as e:
        print(f"Gemini injoignable : {e}", file=sys.stderr)
        return
    print(f"Gemini : modèle {model}", file=sys.stderr)
    done = 0
    for item in todo[:MAX]:
        try:
            out = summarize(model, item, key)
        except urllib.error.HTTPError as e:
            msg = e.read()[:200]
            if e.code == 429:
                print("Limite gratuite atteinte : on reprendra à la prochaine collecte.", file=sys.stderr)
                break
            print(f"Erreur {e.code} pour {item['titre'][:50]} : {msg!r}", file=sys.stderr)
            if e.code in (400, 401, 403, 404):
                break
            continue
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError, IndexError) as e:
            print(f"Réponse inutilisable pour {item['titre'][:50]} : {str(e)[:150]}", file=sys.stderr)
            continue
        resume = str(out.get("resume", "")).strip()
        if len(resume) >= 40:
            item["resume"] = resume
            for k in ("questions", "resultat"):
                v = str(out.get(k, "")).strip()
                if v and not re.search(r"non précisé|n'est pas (indiqué|précisé)|ne (le )?précise pas", v, re.I):
                    item[k] = v
            item["ia_libre"] = model
            done += 1
        time.sleep(PAUSE)
    datastore.save(store, changed=done > 0)
    print(f"{done} résumés rédigés avec Gemini ({model}).", file=sys.stderr)


if __name__ == "__main__":
    main()
