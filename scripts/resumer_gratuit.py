#!/usr/bin/env python3
"""Résumés clairs des décisions avec GitHub Models (gratuit, depuis GitHub Actions).

Utilise le jeton GITHUB_TOKEN du flux de travail (permission « models: read »). Si le service
n'est pas disponible ou que la limite quotidienne est atteinte, le site garde le résumé
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

ENDPOINTS = ["https://models.github.ai/inference/chat/completions", "https://models.inference.ai.azure.com/chat/completions"]
ENDPOINT = ENDPOINTS[0]
MODELS = [m for m in os.environ.get("MODELES", "openai/gpt-4.1-mini,openai/gpt-4o-mini").split(",") if m]


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *a, **k):  # une redirection transformerait la requête POST en GET
        return None


OPENER = urllib.request.build_opener(NoRedirect)
MAX = int(os.environ.get("MAX_RESUMES", "40"))

CONSIGNE = """Tu rédiges, en français juridique québécois clair, le résumé d'une décision pour des avocats en droit criminel et pénal.
On te donne l'intitulé, le tribunal et la classification SOQUIJ/CanLII (mots-clés séparés par « — »).
Réponds UNIQUEMENT en JSON : {"resume": "...", "questions": "...", "resultat": "..."}
- resume : 2 ou 3 phrases complètes et fluides expliquant de quoi il s'agit et ce que le tribunal a décidé.
- questions : la ou les questions en litige, en phrase(s) interrogative(s) claire(s).
- resultat : l'issue en une phrase courte.
Règles : n'utilise que l'information fournie; n'invente aucun fait, nom, article ou résultat; si un élément manque, dis-le sobrement.
Ne nomme jamais un adolescent ou une victime mineure (LSJPA). Si la classification est en anglais, rédige quand même en français."""


def call(model, item, token, endpoint=None):
    body = {
        "model": model,
        "temperature": 0.2,
        "response_format": {"type": "json_object"},
        "messages": [
            {"role": "system", "content": CONSIGNE},
            {"role": "user", "content": f"Intitulé : {item['titre']}\nRéférence : {item.get('reference', '')}\n"
                                        f"Tribunal : {item.get('tribunal', '')}\nClassification : {item.get('source_resume', '')}"},
        ],
    }
    req = urllib.request.Request(endpoint or ENDPOINT, data=json.dumps(body).encode(), method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json",
        "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"})
    with OPENER.open(req, timeout=60) as r:
        raw = r.read()
        status, ctype = r.status, r.headers.get("Content-Type", "")
    try:
        out = json.loads(raw)
        content = out["choices"][0]["message"]["content"] or ""
        content = re.sub(r"^```(?:json)?\s*|\s*```$", "", content.strip())
        return json.loads(content)
    except (ValueError, KeyError, IndexError) as e:
        raise ValueError(f"réponse {status} {ctype} : {raw[:300]!r}") from e


def main():
    token = os.environ.get("GITHUB_TOKEN")
    if not token:
        print("Pas de GITHUB_TOKEN : résumés gratuits désactivés.", file=sys.stderr)
        return
    store = datastore.load()
    todo = [i for i in store["items"] if i["col"] == "decisions" and not i.get("ia") and not i.get("ia_libre") and i.get("source_resume")]
    todo.sort(key=lambda i: i.get("trouve_le", ""), reverse=True)
    done, model = 0, MODELS[0]
    try:
        cat = OPENER.open(urllib.request.Request("https://models.github.ai/catalog/models", headers={
            "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}), timeout=30).read()
        print("Catalogue :", cat[:400], file=sys.stderr)
    except Exception as e:  # noqa: BLE001
        print("Catalogue indisponible :", str(e)[:200], file=sys.stderr)
    # choisit l'adresse et le modèle qui répondent vraiment
    global ENDPOINT
    probe = todo[0] if todo else None
    if probe:
        ok = False
        for ep in ENDPOINTS:
            for m in MODELS + [x.split("/")[-1] for x in MODELS]:
                try:
                    call(m, probe, token, ep)
                    ENDPOINT, model, ok = ep, m, True
                    break
                except Exception as e:  # noqa: BLE001
                    print(f"Essai {ep} / {m} : {str(e)[:160]}", file=sys.stderr)
            if ok:
                break
        if not ok:
            print("GitHub Models indisponible : le résumé automatique sans IA est conservé.", file=sys.stderr)
            return
        print(f"GitHub Models : {ENDPOINT} / {model}", file=sys.stderr)
    for item in todo[:MAX]:
        try:
            out = call(model, item, token)
        except urllib.error.HTTPError as e:
            if e.code == 429:
                print("Limite gratuite atteinte : on reprendra à la prochaine collecte.", file=sys.stderr)
                break
            if e.code in (400, 404) and len(MODELS) > 1 and model == MODELS[0]:
                model = MODELS[1]
                print(f"Modèle indisponible, essai avec {model}", file=sys.stderr)
                continue
            print(f"Erreur {e.code} pour {item['titre'][:50]} : {e.read()[:200]!r}", file=sys.stderr)
            if e.code in (401, 403):
                break
            continue
        except (urllib.error.URLError, TimeoutError, ValueError, KeyError) as e:
            print(f"Réponse inutilisable pour {item['titre'][:50]} : {e}", file=sys.stderr)
            continue
        resume = str(out.get("resume", "")).strip()
        if len(resume) < 40:
            continue
        item["resume"] = resume
        for k in ("questions", "resultat"):
            v = str(out.get(k, "")).strip()
            if v and not re.search(r"non précisé|n'est pas (indiqué|précisé)", v, re.I):
                item[k] = v
        item["ia_libre"] = model
        done += 1
        time.sleep(4.5)  # respecte la limite de requêtes par minute du palier gratuit
    datastore.save(store, changed=done > 0)
    print(f"{done} résumés rédigés avec GitHub Models ({model}).", file=sys.stderr)


if __name__ == "__main__":
    main()
