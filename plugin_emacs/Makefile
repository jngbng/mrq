EMACS ?= emacs
ELPA  := $(CURDIR)/.elpa
STAMP := $(ELPA)/.deps-ok
SRC   := $(wildcard *.el)
TESTS := $(wildcard test/*-test.el)

# 사용자의 ~/.emacs.d 를 건드리지 않는다. -Q 라 init 도 읽지 않는다.
BATCH = $(EMACS) -Q -batch \
	  --eval '(setq package-user-dir "$(ELPA)")' \
	  --eval '(package-initialize)' \
	  -L $(CURDIR) -L $(CURDIR)/test

.PHONY: test lint deps conformance clean

# 평소에는 부를 필요가 없다 — test/lint/conformance 가 $(STAMP) 를 의존하므로
# 없으면 알아서 설치한다. `make deps` 는 다시 받고 싶을 때의 강제 경로다.
deps:
	@rm -f $(STAMP)
	@$(MAKE) $(STAMP)

# markdown-mode 를 $(ELPA) 에만 설치한다. 스탬프가 .elpa/ 안에 있으므로
# .elpa/ 를 지우면 다음 test 에서 다시 설치된다.
$(STAMP):
	$(EMACS) -Q -batch \
	  --eval '(setq package-user-dir "$(ELPA)")' \
	  --eval '(require (quote package))' \
	  --eval '(add-to-list (quote package-archives) (cons "melpa" "https://melpa.org/packages/"))' \
	  --eval '(package-initialize)' \
	  --eval '(unless (package-installed-p (quote markdown-mode)) (package-refresh-contents) (package-install (quote markdown-mode)))'
	@mkdir -p $(ELPA)
	@touch $@
	@echo "deps -> $(ELPA)"

test: $(STAMP)
	$(BATCH) $(foreach t,$(TESTS),-l $(t)) -f ert-run-tests-batch-and-exit

conformance: $(STAMP)
	$(BATCH) -l test/mrq-anchor-test.el \
	  --eval '(ert-run-tests-batch-and-exit "conformance")'

# elisp 에서 가장 싼 방어다 — 오타, 잘못된 인자 수, 쓰이지 않는 변수,
# 미선언 동적 변수를 전부 여기서 잡는다.
lint: $(STAMP)
	$(BATCH) --eval '(setq byte-compile-error-on-warn t)' -f batch-byte-compile $(SRC)
	$(BATCH) -l $(CURDIR)/tools/checkdoc-gate.el -f mrq-checkdoc-gate $(SRC)
	@$(MAKE) clean

clean:
	rm -f *.elc test/*.elc
