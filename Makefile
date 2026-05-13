.PHONY: test eval eval-suite compile plugin-validate package-smoke sync-vendor clean verify

PYTHON ?= python3

test:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m unittest discover -s tests -v

eval:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m lateral eval
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m lateral eval --fixtures eval/fixtures/mvp_tasks.json

eval-suite:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m lateral eval-suite \
		--fixtures eval/fixtures/mvp_tasks.json \
		--fixtures eval/fixtures/robust_router_tasks.json \
		--fixtures eval/fixtures/stress_router_tasks.json

compile:
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m py_compile lateral/*.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m py_compile plugins/lateral-mode/scripts/*.py
	PYTHONDONTWRITEBYTECODE=1 $(PYTHON) -m py_compile plugins/lateral-mode/vendor/lateral/*.py

plugin-validate:
	claude plugin validate ./plugins/lateral-mode
	claude plugin validate .

package-smoke:
	tmp="$$(mktemp -d)"; \
	$(PYTHON) -m venv "$$tmp/venv"; \
	"$$tmp/venv/bin/python" -m pip install -q .; \
	"$$tmp/venv/bin/lateral" install-global --home "$$tmp/home"; \
	"$$tmp/venv/bin/lateral" eval-suite \
		--fixtures eval/fixtures/mvp_tasks.json \
		--fixtures eval/fixtures/robust_router_tasks.json \
		--fixtures eval/fixtures/stress_router_tasks.json; \
	LATERAL_HOME="$$tmp/home" "$$tmp/venv/bin/lateral" outcome --path "$$tmp/repo" --resolved yes --rating 4 --validation passed; \
	LATERAL_HOME="$$tmp/home" "$$tmp/venv/bin/lateral" metrics --path "$$tmp/repo"; \
	rm -rf "$$tmp"

sync-vendor:
	rsync -a --delete --exclude '__pycache__' lateral/ plugins/lateral-mode/vendor/lateral/

clean:
	rm -rf lateral/__pycache__ tests/__pycache__ build dist *.egg-info
	find . -type d -name '__pycache__' -prune -exec rm -rf {} +
	find . -name '*.pyc' -delete

verify: test eval eval-suite compile plugin-validate package-smoke clean
