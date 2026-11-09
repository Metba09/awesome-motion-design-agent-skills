# Real work lives in scripts/*; these targets are thin entry points. Offline, no input.
SHELL := bash
PYTHON ?= python3
.DEFAULT_GOAL := help
.PHONY: help setup check test validate lint format links schemas skills guard mock build snapshot verify-snapshot verify-bundle pack offline clean

help: ## List targets
	@grep -E '^[a-z-]+:.*## ' $(MAKEFILE_LIST) | awk -F':.*## ' '{printf "  make %-16s %s\n", $$1, $$2}'

setup: ## Idempotent offline setup (creates .env, dist/, out/)
	./setup.sh
check: ## Full gate, run before concluding
	./scripts/check.sh
test: ## Unit tests
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
validate: ## SKILL.md frontmatter, JSON, public-safety
	$(PYTHON) scripts/validate-repo.py
lint: ## Python, shell, Markdown, whitespace
	./scripts/lint.sh
format: ## Mechanical fixes (trailing whitespace, final newline)
	./scripts/format.sh
links: ## Local Markdown links and anchors; writes docs/external-links.json
	$(PYTHON) scripts/check-links.py --external-json docs/external-links.json
schemas: ## Media jobs against the schema (valid and invalid fixtures)
	$(PYTHON) scripts/validate-json.py
	$(PYTHON) scripts/validate-json.py --expect-invalid tests/fixtures/invalid/*.json
skills: ## Standalone skill payload checks
	$(PYTHON) scripts/verify-skill-packages.py
guard: ## Static check: no network in the tooling
	$(PYTHON) scripts/offline-guard.py
mock: ## Run every sample job through the offline mock provider into out/
	for job in examples/media-jobs/*.json; do $(PYTHON) scripts/mock-provider.py "$$job"; done
build: ## Build and verify the six skill ZIPs into dist/
	$(PYTHON) scripts/build-skill-zips.py
snapshot: ## Refresh MANIFEST.sha256 and SNAPSHOT.json
	$(PYTHON) scripts/snapshot.py create
verify-snapshot: ## Fail if a file differs from MANIFEST.sha256
	$(PYTHON) scripts/snapshot.py verify
verify-bundle: ## BUNDLE.json vs repo (add ARGS="--livrable DIR" to check the mirror too)
	$(PYTHON) scripts/sandbox/verify_bundle.py $(ARGS)
pack: ## Deterministic bundle ZIP in dist/bundle/
	mkdir -p dist/bundle && $(PYTHON) scripts/snapshot.py pack dist/bundle/awesome-motion-design-sandbox.zip
offline: ## Run `make check` with the network cut (isolated namespace)
	./scripts/run-offline.sh make check
clean: ## Remove generated dist/ and out/
	rm -rf dist out
