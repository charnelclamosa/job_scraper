# ---- Configuration ----
IMAGE_NAME ?= job-scraper
IMAGE_TAG ?= latest
CONTAINER_NAME ?= job-scraper-container
DOCKERFILE ?= Dockerfile
CONTEXT ?= .
PORT ?= 8080
CV ?= data/skills.json
SITE ?= all
LOCATION ?= Philippines
DAYS ?= 30
LIMIT ?= 100
MIN_MATCHES ?= 3
OUTPUT_DIR  ?= output
SLUG := $(shell echo "$(QUERY)" | tr '[:upper:]' '[:lower:]' | sed -E 's/[^a-z0-9]+/-/g; s/^-+|-+$$//g')

.PHONY: all build run run-reload logs python-cli bash stop clean

all: build run

## Build the Docker image
build:
	docker build -f $(DOCKERFILE) -t $(IMAGE_NAME):$(IMAGE_TAG) $(CONTEXT)

## Run the container (production-style, matches Dockerfile CMD)
# Usage: 
# $ make run QUERY="cloud engineer" DAYS=7
# $ make run QUERY="cloud engineer" SITE="jobstreet" DAYS=7
# $ make run QUERY="cloud engineer" SITE="indeed" DAYS=7
run:
	@test -n "$(QUERY)" || (echo "QUERY is required, e.g. make match QUERY=\"embedded engineer\""; exit 1)
	@test -f "$(CV)" || (echo "CV file not found: $(CV)"; exit 1)
	@mkdir -p $(OUTPUT_DIR)
	docker run --rm -it \
		--name $(CONTAINER_NAME) \
		--user $(shell id -u):$(shell id -g) \
		-v $(CURDIR):/app \
		$(IMAGE_NAME):$(IMAGE_TAG) \
			python python/main.py \
				--cv $(CV) \
				$(if $(filter-out all,$(SITE)),--site $(SITE)) \
				--query "$(QUERY)" \
				--location "$(LOCATION)" \
				--days $(DAYS) \
				--limit $(LIMIT) \
				--min-matches $(MIN_MATCHES) \
				--csv $(OUTPUT_DIR)/$(SLUG)-$(SITE)-$(DAYS)d.csv

## Run with hot reload: mounts local code + gunicorn --reload
## Requires gunicorn and your app deps to already be in the image's venv.
run-reload:
	docker run --rm -it \
		--name $(CONTAINER_NAME)-reload \
		-p $(PORT):8080 \
		-v $(CURDIR):/app \
		--entrypoint gunicorn \
		$(IMAGE_NAME):$(IMAGE_TAG) \
		-b 0.0.0.0:8080 -w 4 --reload python.server:app

## Stream logs from the running container
logs:
	docker logs -f $(CONTAINER_NAME)

## Enter a Python CLI inside a new container (uses the venv on PATH)
python-cli:
	docker run --rm -it \
		--name $(CONTAINER_NAME)-python \
		--entrypoint python \
		$(IMAGE_NAME):$(IMAGE_TAG)

## Enter a bash shell inside a new container
bash:
	docker run --rm -it \
		--name $(CONTAINER_NAME)-bash \
		--entrypoint bash \
		$(IMAGE_NAME):$(IMAGE_TAG)

## Stop the running container (if named/detached)
stop:
	docker stop $(CONTAINER_NAME) || true

## Remove the built image
clean:
	docker rmi $(IMAGE_NAME):$(IMAGE_TAG) || true