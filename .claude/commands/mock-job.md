---
description: Rejouer un job média avec le fournisseur simulé (aucun réseau, aucune clé)
argument-hint: "[examples/media-jobs/<job>.json]"
---

Sans argument, lance `make mock`. Avec un argument, lance `python3 scripts/mock-provider.py $ARGUMENTS`. Les sorties sont dans `out/<id>/`. Précise à l'utilisateur que ce sont des substituts : `qa-report.json` indique « not-evaluated » et aucune sortie réelle de fournisseur n'existe.
