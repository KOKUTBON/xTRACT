VENV ?= .venv
PYTHON ?= $(shell if [ -f $(VENV)/bin/python ]; then echo $(VENV)/bin/python; else echo python3; fi)
RUFF ?= $(shell if [ -f $(VENV)/bin/ruff ]; then echo $(VENV)/bin/ruff; else echo ruff; fi)

.PHONY: lint format format-check test ci run
lint:
	$(RUFF) check .
format:
	$(RUFF) format .
format-check:
	$(RUFF) format --check .
test:
	$(PYTHON) -m unittest discover -s tests -p 'test_*.py' -v
ci: lint format-check test
run:
	$(PYTHON) xtract.py serve
