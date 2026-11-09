---
description: Construire et vérifier les six ZIP de skills (reproductibles)
---

Lance `make build`. Les ZIP, `SHA256SUMS` et `release-provenance.json` sont écrits dans `dist/` puis vérifiés par `scripts/verify-skill-packages.py`. Seul `skills/` est empaqueté, jamais `vendor/`.
