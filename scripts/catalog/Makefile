# 6thSense buyer-facing data catalog — ingest tooling.
#
#   make dev         run the WHOLE catalog locally and open it in a browser
#   make fixtures    synthetic takes at the delivered shape  ->  sample/takes/
#   make ingest      takes -> bundle                         ->  sample/bundle/
#   make validate    re-validate the bundle against both JSON Schemas
#   make upload      push the bundle to the private S3 bucket
#
# `make dev` is the one to start with: Postgres, migrations, the guest account,
# the API on the local-disk driver and the Vite dev server, in one command. It
# needs no AWS -- see dev_local.sh for how the same code reaches S3 later.
#
# `make` on its own runs fixtures + ingest + validate + test, which is the whole
# data half of the catalog end to end. The site half lives in ../../frontend and
# ../../backend and is not built here.
#
# Run from anywhere:  make -C scripts/catalog
# Full pipeline docs: ../../docs/catalog/README.md

SHELL   := /bin/bash
ROOT    := $(patsubst %/,%,$(dir $(abspath $(lastword $(MAKEFILE_LIST)))))
PYTHON  ?= python3
TAKES   ?= $(ROOT)/sample/takes
BUNDLE  ?= $(ROOT)/sample/bundle
# The delivered corpus: ~30 clips of 30-45 s, about twenty minutes in total.
CLIPS   ?= 30
SEED    ?= 7
MIN_S   ?= 30
MAX_S   ?= 45
PREFIX  ?= $(or $(CATALOG_S3_PREFIX),v1/)

.DEFAULT_GOAL := all
.PHONY: all dev dev-stop dev-rebuild fixtures ingest validate test stats upload clean deps help

## all: fixtures + ingest + validate + unit tests
all: fixtures ingest validate test

## dev: run the whole catalog locally (Postgres + API + site) and open it
dev:
	$(ROOT)/dev_local.sh

## dev-rebuild: same as `dev`, but regenerate the corpus first
dev-rebuild:
	$(ROOT)/dev_local.sh --rebuild

## dev-stop: tear down a local run left behind by a hard kill
dev-stop:
	$(ROOT)/dev_local.sh --stop

## deps: install the Python requirements (jsonschema, numpy, pyyaml, pytest)
deps:
	$(PYTHON) -m pip install --quiet -r $(ROOT)/requirements.txt

## fixtures: generate $(CLIPS) synthetic takes into sample/takes (needs ffmpeg + numpy)
##           FIXTURE_FLAGS=--with-gaps builds the missing-modality corpus instead
fixtures:
	cd $(ROOT)/fixtures && $(PYTHON) generate_fixtures.py \
		--out $(TAKES) --clips $(CLIPS) --seed $(SEED) \
		--min-seconds $(MIN_S) --max-seconds $(MAX_S) $(FIXTURE_FLAGS)

## ingest: build the catalog bundle from sample/takes
ingest:
	cd $(ROOT) && $(PYTHON) -m ingest.catalog_ingest build \
		--takes $(TAKES) --out $(BUNDLE) --posters --previews

## validate: re-validate the emitted bundle against both JSON Schemas
validate:
	cd $(ROOT) && $(PYTHON) -m ingest.catalog_ingest validate --out $(BUNDLE)

## test: unit tests for the rules a passing bundle cannot prove (needs pytest)
test:
	cd $(ROOT) && $(PYTHON) -m pytest tests -q

## stats: print collection totals and facet counts
stats:
	cd $(ROOT) && $(PYTHON) -m ingest.catalog_ingest stats --out $(BUNDLE)

## upload: sync $(BUNDLE) to s3://$$CATALOG_S3_BUCKET/$(PREFIX)  (needs boto3 + creds)
upload:
	$(PYTHON) $(ROOT)/upload_bundle.py --bundle $(BUNDLE) --prefix $(PREFIX)

## clean: delete generated takes and the bundle (never the sources)
clean:
	rm -rf $(ROOT)/sample $(ROOT)/.ruff_cache $(ROOT)/.pytest_cache

help:
	@grep -hE '^## ' $(MAKEFILE_LIST) | sed 's/^## /  /'
