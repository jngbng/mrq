.PHONY: test test-cli test-emacs test-vscode conformance lint deps

test: test-cli test-emacs test-vscode

test-cli:
	cd cli && python -m pytest

test-emacs:
	$(MAKE) -C plugin_emacs test

test-vscode:
	@echo "plugin_vscode 는 아직 없습니다 (계획 5)"

conformance:
	$(MAKE) -C plugin_emacs conformance

lint:
	cd cli && ruff format --check . && ruff check .
	$(MAKE) -C plugin_emacs lint

deps:
	cd cli && uv sync
	$(MAKE) -C plugin_emacs deps
