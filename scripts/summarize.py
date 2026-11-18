#!/usr/bin/env python3
"""Résumés en français, destinés aux criminalistes, pour les nouveaux éléments.

Utilise l'API Claude si la variable ANTHROPIC_API_KEY est définie (secret GitHub).
Sans clé, le script ne fait rien : le site continue de fonctionner avec les
titres, les liens et les descriptions des sources.

Ne traite que les onglets « decisions » et « juridique », et au plus MAX_PAR_COLLECTE
éléments par exécution pour borner le coût.
"""
import json
import os
import sys

import anthropic

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA = os.path.join(ROOT, "data", "items.json")
MODEL = "claude-opus-5-5"
MAX_PAR_COLLECTE = int(os.environ.get("MAX_PAR_COLLECTE", "30"))

SYSTEM = """Tu rédiges une veille juridique pour des avocats criminalistes du Québec (défense et poursuite).
Pour chaque élément, tu reçois le titre, la source, la date et la description fournie par la source
(pour les décisions : la classification CanLII/SOQUIJ). Rédige en français juridique québécois, précis et sobre.

Règles :
- Appuie-toi uniquement sur l'information fournie. N'invente aucun fait, article de loi, nom, juge ou résultat.
  Si une information manque, laisse le champ vide plutôt que de deviner.
- « resume » : 2 ou 3 phrases sur les faits et le raisonnement (ou le contenu du projet de loi / de la nouvelle).
- « questions » (décisions seulement) : la ou les questions en litige, en une phrase.
- « resultat » (décisions seulement) : l'issue en quelques mots (ex. « Appel accueilli; nouveau procès ordonné »).
- « impact » : 1 ou 2 phrases sur la portée pratique pour un criminaliste (argument utile, point de vigilance, changement de pratique).
- « important » : true seulement si l'élément change ou précise l'état du droit de façon notable, sinon false.
- Chambre de la jeunesse / LSJPA : n'identifie jamais l'adolescent, une victime ou un témoin mineur; garde l'intitulé anonymisé.
- Personnes accusées : rappelle la présomption d'innocence s'il n'y a pas de verdict de culpabilité."""

SCHEMA = {
    "type": "object",
    "properties": {
        "resume": {"type": "string"},
        "questions": {"type": "string"},
        "resultat": {"type": "string"},
        "impact": {"type": "string"},
        "important": {"type": "boolean"},
    },
    "required": ["resume", "questions", "resultat", "impact", "important"],
    "additionalProperties": False,
}


def prompt_for(item):
    lignes = [
        f"Type : {'décision' if item['col'] == 'decisions' else 'législation / profession'}",
        f"Titre : {item.get('titre', '')}",
        f"Référence : {item.get('reference', '')}",
        f"Tribunal ou catégorie : {item.get('tribunal') or item.get('categorie', '')}",
        f"Source : {item.get('source', '')}",
        f"Date : {item.get('date', '')}",
        f"Description de la source : {item.get('resume', '') or '(aucune)'}",
    ]
    return "\n".join(lignes)


def summarize(client, item):
    response = client.beta.messages.create(
        model=MODEL,
        max_tokens=16000,
        betas=["server-side-fallback-2026-07-01"],
        fallbacks="default",
        system=SYSTEM,
        output_config={"effort": "low", "format": {"type": "json_schema", "schema": SCHEMA}},
        messages=[{"role": "user", "content": prompt_for(item)}],
    )
    if response.stop_reason != "end_turn":
        raise RuntimeError(f"arrêt inattendu : {response.stop_reason}")
    text = next(b.text for b in response.content if b.type == "text")
    out = json.loads(text)
    usage = response.usage
    return out, usage.input_tokens, usage.output_tokens


def main():
    if not os.environ.get("ANTHROPIC_API_KEY"):
        print("Pas de clé ANTHROPIC_API_KEY : résumés désactivés.", file=sys.stderr)
        return
    with open(DATA, encoding="utf-8") as f:
        store = json.load(f)
    todo = [i for i in store["items"] if i["col"] in ("decisions", "juridique") and "ia" not in i]
    todo = todo[:MAX_PAR_COLLECTE]
    if not todo:
        print("Aucun nouvel élément à résumer.", file=sys.stderr)
        return

    client = anthropic.Anthropic(max_retries=3)
    done = tokens_in = tokens_out = 0
    for item in todo:
        try:
            out, tin, tout = summarize(client, item)
        except anthropic.AuthenticationError:
            print("Clé API refusée : vérifiez le secret ANTHROPIC_API_KEY.", file=sys.stderr)
            break
        except anthropic.PermissionDeniedError as e:
            print(f"Accès refusé (crédit épuisé ou limite atteinte ?) : {e.message}", file=sys.stderr)
            break
        except anthropic.RateLimitError:
            print("Limite de débit atteinte; on reprendra à la prochaine collecte.", file=sys.stderr)
            break
        except anthropic.APIStatusError as e:
            print(f"Erreur API ({e.status_code}) pour {item['id']} : {e.message}", file=sys.stderr)
            continue
        except anthropic.APIConnectionError:
            print("Erreur réseau; on reprendra à la prochaine collecte.", file=sys.stderr)
            break
        except (RuntimeError, ValueError, StopIteration) as e:
            print(f"Réponse inutilisable pour {item['id']} : {e}", file=sys.stderr)
            continue
        item["source_resume"] = item.get("resume", "")
        item["resume"] = out["resume"].strip() or item.get("resume", "")
        for k in ("questions", "resultat", "impact"):
            if out[k].strip():
                item[k] = out[k].strip()
        item["important"] = bool(out["important"])
        item["ia"] = True
        done += 1
        tokens_in += tin
        tokens_out += tout

    with open(DATA, "w", encoding="utf-8") as f:
        json.dump(store, f, ensure_ascii=False, indent=1)
    cout = tokens_in / 1e6 * 4 + tokens_out / 1e6 * 20
    print(f"{done} résumés; {tokens_in} jetons en entrée, {tokens_out} en sortie; coût estimé {cout:.3f} $ US", file=sys.stderr)


if __name__ == "__main__":
    main()
