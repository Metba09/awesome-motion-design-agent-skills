# vendor/

Emplacement des copies figées, en lecture seule, de ce qui est autrement téléchargé par `npx skills add`.

| Dossier | Origine | Épinglage |
| --- | --- | --- |
| `remotion-skills/remotion-best-practices/` | dépôt `remotion-dev/skills` | voir [PROVENANCE.json](PROVENANCE.json) (commit, empreinte de l'arbre) |

**Absent de ce dépôt public.** Le dépôt amont ne contient pas de fichier de licence : la copie n'est donc pas publiée ici et `vendor/remotion-skills/` est dans `.gitignore`.
Pour la restaurer en privé : dépaqueter le bundle complet archivé dans le dépôt privé `claude-memory`, ou copier `skills/remotion-best-practices` depuis le commit indiqué dans `PROVENANCE.json` (une fois la licence clarifiée avec ses auteurs).

Règles : ne pas modifier, ne pas publier, ne pas l'ajouter aux ZIP de `skills/`.
Les scripts de validation (`validate-repo.py`, `lint-docs.py`, `check-links.py`) ignorent ce dossier.
