UV := $(shell command -v uv 2>/dev/null)
ifeq ($(UV),)
$(error uv 가 필요합니다 — https://docs.astral.sh/uv/getting-started/installation/)
endif

CLI := uv run --directory cli

# ARGS 인자를 통해 테스트 범위를 좁힐 수 있다: make test-cli ARGS="-k anchor"
ARGS ?=

.PHONY: test test-cli test-emacs test-vscode conformance lint fmt deps

test: test-cli test-emacs test-vscode

test-cli:
	$(CLI) python -m pytest $(ARGS)

test-emacs:
	$(MAKE) -C plugin_emacs test

test-vscode:
	@echo "plugin_vscode 는 아직 없습니다 (계획 5)"

conformance:
	$(MAKE) -C plugin_emacs conformance

lint:
	$(CLI) ruff format --check .
	$(CLI) ruff check .
	$(MAKE) -C plugin_emacs lint

fmt:
	$(CLI) ruff format .
	$(CLI) ruff check --fix .

# 평소에는 부를 필요가 없다. 각 타깃이 알아서 갖춘다.
deps:
	uv sync --directory cli
	$(MAKE) -C plugin_emacs deps
