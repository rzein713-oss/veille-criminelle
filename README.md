# Veille criminelle Québec

Site public de veille en droit criminel québécois : décisions, législation, nouvelles de la profession et revue de presse.
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
