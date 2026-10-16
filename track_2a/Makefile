.PHONY: run build test sample eval extension schema

IMAGE ?= william
PORT ?= 8000
# Judges' convention: LLM_NAME / LLM_BASE_URL / LLM_API_KEY from the environment (or a local .env)
ENV_FILE := $(wildcard .env)
DOCKER_ENV = $(if $(ENV_FILE),--env-file .env,) -e LLM_NAME -e LLM_BASE_URL -e LLM_API_KEY

build:
	docker build -t $(IMAGE) .

# Start the William API (web form at http://localhost:$(PORT)/, docs at /docs)
run: build
	docker run --rm -p $(PORT):8000 $(DOCKER_ENV) $(IMAGE)

# Offline checks: provenance verifier, schema validation, re-verification of stored Apertus outputs
test: build
	docker run --rm $(IMAGE) python -m pytest -q tests

# Live: extract the 14-document sample with Apertus (needs LLM_API_KEY)
sample: build
	docker run --rm $(DOCKER_ENV) -v "$(CURDIR)/eval:/app/eval" $(IMAGE) sh -c \
	  'python -m william extract --no-summary $$(grep -v "^#" data/sample/urls.txt | cut -f3) -o eval/sample_live.json && \
	   python -m william.evaluate stats eval/sample_live.json data/sample/urls.txt'

# Re-print the evaluation table from the stored run (no API calls)
eval: build
	docker run --rm $(IMAGE) python -m william.evaluate stats eval/sample_70b_reverified.json data/sample/urls.txt

schema: build
	docker run --rm $(IMAGE) python -m william schema

# Zip the Firefox extension (load it via about:debugging -> This Firefox -> Load Temporary Add-on)
extension:
	cd src/extension && zip -r ../../william-firefox.zip . -x "*.DS_Store"
