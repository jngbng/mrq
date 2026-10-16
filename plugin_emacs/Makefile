EMACS ?= emacs
ELPA  := $(CURDIR)/.elpa
SRC   := $(wildcard *.el)
TESTS := $(wildcard test/*-test.el)

# 사용자의 ~/.emacs.d 를 건드리지 않는다. -Q 라 init 도 읽지 않는다.
BATCH = $(EMACS) -Q -batch \
	  --eval '(setq package-user-dir "$(ELPA)")' \
	  --eval '(package-initialize)' \
	  -L $(CURDIR) -L $(CURDIR)/test

.PHONY: test lint deps conformance clean

deps:
	$(EMACS) -Q -batch \
	  --eval '(setq package-user-dir "$(ELPA)")' \
	  --eval '(require (quote package))' \
	  --eval '(add-to-list (quote package-archives) (cons "melpa" "https://melpa.org/packages/"))' \
	  --eval '(package-initialize)' \
	  --eval '(unless (package-installed-p (quote markdown-mode)) (package-refresh-contents) (package-install (quote markdown-mode)))'
	@echo "deps -> $(ELPA)"

test:
	@$(BATCH) --eval '(unless (locate-library "markdown-mode") (message "markdown-mode 가 없습니다 — 먼저 `make deps` 를 실행하세요") (kill-emacs 1))'
	$(BATCH) $(foreach t,$(TESTS),-l $(t)) -f ert-run-tests-batch-and-exit

conformance:
	$(BATCH) -l test/mrq-anchor-test.el \
	  --eval '(ert-run-tests-batch-and-exit "conformance")'

# elisp 에서 가장 싼 방어다 — 오타, 잘못된 인자 수, 쓰이지 않는 변수,
# 미선언 동적 변수를 전부 여기서 잡는다.
lint:
	$(BATCH) --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile $(SRC)
	$(BATCH) -l $(CURDIR)/tools/checkdoc-gate.el -f mrq-checkdoc-gate $(SRC)
	@$(MAKE) clean

clean:
	rm -f *.elc test/*.elc
