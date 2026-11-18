# Revue en droit criminel et pénal — Sub Rosa Connect

Site public de Sub Rosa Connect : décisions, législation, nouvelles de la profession et revue de presse en droit criminel et pénal au Québec (incluant le pénal réglementaire et les cours municipales).
Il fonctionne entièrement sur GitHub, gratuitement, sans abonnement Claude.

- **Site** : `index.html`, publié par GitHub Pages à l'adresse `subrosaconnect.ca` (fichier `CNAME`).
- **Données** : `data/items.json`, conservées 120 jours.
- **Collecte** : `scripts/collect.py` (Python, bibliothèque standard seulement), lancé deux fois par jour par `.github/workflows/collecte.yml`.

## Sources

| Onglet | Sources |
|---|---|
| Décisions | CanLII (Cour d'appel, Cour supérieure, Cour du Québec incl. Chambre de la jeunesse, cours municipales), Cour suprême du Canada |
| Législation et Barreau | LEGISinfo (projets de loi fédéraux), Droit-inc, Association du Barreau canadien |
| Revue de presse | Google Actualités (recherches par thème : politique et justice, système carcéral, police, crimes et procès, tendances) |

## Lancer une collecte à la main

Onglet **Actions** → **Collecte quotidienne** → **Run workflow**.

## Mise en ligne (une seule fois)

1. **Settings → Pages** : Source = *Deploy from a branch*, Branch = `main`, dossier `/ (root)`.
2. **Settings → Pages → Custom domain** : `subrosaconnect.ca`, puis cocher *Enforce HTTPS* quand c'est offert.
3. **GoDaddy → DNS** du domaine `subrosaconnect.ca` :
   - 4 enregistrements `A`, Nom `@` : `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153` (supprimer tout autre enregistrement `A` sur `@`, y compris « Parked »).
   - 1 enregistrement `CNAME`, Nom `www`, Valeur `rzein713-oss.github.io`.
4. **Settings → Actions → General → Workflow permissions** : *Read and write permissions*.

## Résumés par IA (optionnel)

`scripts/summarize.py` rédige, pour chaque nouvelle décision et chaque élément « Législation et Barreau », les questions en litige, un résumé, le résultat et l'impact pratique (modèle Claude Opus 5.5, effort bas).

- Activation : ajouter un secret `ANTHROPIC_API_KEY` dans **Settings → Secrets and variables → Actions**.
- Sans clé, rien ne change : le site garde les descriptions des sources.
- Au plus 30 éléments par collecte (`MAX_PAR_COLLECTE`). Le coût estimé de chaque collecte est affiché dans le journal de l'action.
- Fixer une limite de dépenses mensuelle dans la console Anthropic (Settings → Limits).
