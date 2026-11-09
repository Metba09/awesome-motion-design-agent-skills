# Bundle hors-ligne (sandbox Chat Claude.ai)

Ce dépôt est un snapshot hermétique de `awesome-motion-design-agent-skills` : il s'installe et se vérifie sans réseau.

## Constat sur les dépendances

Le dépôt amont est du contenu (Markdown, JSON) plus des scripts Python en bibliothèque standard. Il ne contient ni `package.json`, ni lockfile, ni dépendance Python. Il n'y avait donc rien à « vendorer » côté code : le travail a porté sur la logique cachée, les appels réseau et les ressources téléchargées à la volée.

## Ce qui a changé par rapport à l'amont

| Élément | Avant | Maintenant |
| --- | --- | --- |
| Validation de frontmatter, manifestes et chemins privés | Python en ligne dans `skills-validate.yml` | `scripts/validate-repo.py` (le workflow l'appelle) |
| Vérification des liens | `lychee` en CI, réseau requis | `scripts/check-links.py` : liens et ancres locaux ; URL externes inventoriées dans `docs/external-links.json`, jamais ouvertes |
| Empaquetage des ZIP de skills | étapes shell/Python dans `skills-release.yml` | `scripts/build-skill-zips.py` : ZIP reproductibles, vérifiés |
| Jobs média | aucun exemple, fournisseurs réseau | `examples/media-jobs/`, `scripts/mock-provider.py`, `scripts/validate-json.py` |
| Lint, format | aucun | `scripts/lint-docs.py`, `lint.sh`, `format.sh` (pas de hook) |
| Porte avant conclusion | manuelle | `make check` ; `make offline` la rejoue réseau coupé |
| Installation | `npx skills add` | `setup.sh` idempotent, sans saisie |
| Skill tierce `remotion-best-practices` | téléchargée par `npx` | épinglée par commit dans `vendor/PROVENANCE.json` ; la copie n'est pas publiée ici (licence amont non explicite), elle vit dans l'archive privée |
| Intégrité | aucune | `MANIFEST.sha256` et `SNAPSHOT.json` |

`.github/workflows/skills-release.yml` et `scripts/release-policy.py` n'ont pas été modifiés : ils restent propres à la CI GitHub.

## Intégrité

```bash
make verify-snapshot   # échoue si un fichier est modifié ou manquant
make snapshot          # à relancer après vos propres modifications
make pack              # ZIP déterministe dans dist/bundle/
```

## Limites connues

- Les 70 URL externes du README et des playbooks ne sont pas vérifiées ici ; `docs/external-links.json` les liste avec leur fichier et leur ligne.
- Le mock produit des substituts (PNG, SVG animé, plan, checksums). Il ne remplace ni un fournisseur réel ni une revue visuelle du mouvement.
- La skill Remotion, quand elle est restaurée, se lit mais ne s'exécute pas : Remotion exige Node, npm et un navigateur, absents du bundle.
- `skills-lock.json` garde l'ancien `skillPath` de la skill Remotion (renommée en amont) : voir `vendor/PROVENANCE.json`.
- La licence de la skill Remotion n'est pas explicite en amont : usage privé uniquement, jamais publiée dans ce dépôt.
