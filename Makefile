.PHONY: test test-cli test-emacs test-vscode conformance lint deps

test: test-cli test-emacs test-vscode

test-cli:
	cd cli && python -m pytest

test-emacs:
	@echo "plugin_emacs 는 아직 없습니다 (계획 4)"

test-vscode:
	@echo "plugin_vscode 는 아직 없습니다 (계획 5)"

conformance:
	@echo "적합성 테이블은 첫 에디터 구현과 함께 들어옵니다 (계획 4)"

lint:
	cd cli && ruff format --check . && ruff check .

deps:
	cd cli && uv sync
