# 계획 4 — `plugin_emacs` 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Emacs 에서 소스 ↔ MR 코멘트 왕복을 닫는다 — flymake 로 코멘트를 보고,
`C-c m r` 로 답글을 쓰고, 저장하면 `sync` 가 돈다.

**Architecture:** 일곱 모듈, 의존은 한쪽으로만 흐른다. `mrq-anchor.el` 은 의존 0 의
순수 함수(적합성 테이블의 대상), `mrq-core.el` 은 `review.json` 을 읽는 **유일한**
창구, `mrq-cli.el` 은 프로세스를 띄우는 **유일한** 자리. 나머지 넷은 UI 다.

**Tech Stack:** GNU Emacs 29.1+, `flymake`, `file-notify`, `json-parse-buffer`,
`markdown-mode` 2.5 (`mrq-mode.el` 에서만), ERT, `emacs -Q -batch`.

**Spec:** `docs/plans/2026-10-14-plugin-emacs-design.md` 2부 (§2.1 ~ §2.11)
규범은 `docs/spec/editor.md`, `docs/spec/reanchoring.md` §6,
`docs/spec/repo-layout.md` §4.

## Global Constraints

`editor.md` §1 의 일곱 줄. 전 과제에서 여덟 번째가 추가된다(Task 11).

1. **`review.json` 만 읽는다.** `review.md` 를 파싱하지 않는다(MUST NOT) — 단
   **점을 옮기기 위한 검색은 파싱이 아니다**(Task 11 이 스펙에 넣는 문장)
2. 상태 변경은 `mrq reply`/`state`/`sync` 로만. `review.json` 을 직접 쓰지 않는다(MUST NOT)
3. 위치 보정은 `reanchoring.md` §6 의 범위만
4. **`git` 과 네트워크를 호출하지 않는다**(MUST NOT)
5. `review.json` 을 **파일 감시**로 추적해 진단을 갱신한다(MUST)
6. `schema_version` 을 확인한다. 모르는 버전이면 거부한다(MUST)
7. `testdata/conformance/anchor.json` 을 통과한다(MUST)

추가 제약:

- 접두사 규약: 공개는 `mrq-`, 내부는 `mrq--`. 각 모듈은 자기 파일 이름을 접두사로
  쓴다 (`mrq-core-…`, `mrq-anchor-…`)
- **`make lint` 가 `byte-compile-error-on-warn t` 다.** 경고 하나가 실패다
- `markdown-mode` 는 `plugin_emacs/.elpa/` 에만 설치한다. `~/.emacs.d` 를 건드리지
  않는다(MUST)
- 테스트는 전부 `emacs -Q -batch`. 사용자 설정을 읽지 않는다
- `mrq-anchor.el` 과 `mrq-core.el` 은 Emacs 내장 외에 아무것도 require 하지 않는다

## Review Focus

스펙이 함의하지만 과제의 테스트가 저절로 덮지는 않는 것들. 각 줄의 테스트를
담당 과제에 넣어 뒀다.

1. **`os.replace` 로 바뀐 inode** — CLI 는 temp 파일 + `os.replace` 로 `review.json`
   을 쓴다(`store.py:179`). 파일에 건 inotify watch 는 **첫 쓰기 이후 조용히 죽는다**
   (처음 한 번은 오고 그 뒤로 영영 안 옴). 디렉터리에 걸어야 하고, 테스트는
   **두 번 연속** 고쳐야 그것을 잡는다 → **Task 4**
2. **`.mrq` 가 생기기 전에 연 버퍼** — 사용자는 `mrq pull` 전에 소스를 열어 둔다.
   탐색 실패를 버퍼 로컬에 캐시하면 그 버퍼는 영원히 진단이 안 뜬다 → **Task 3**
3. **`current` 가 다른 MR 로 바뀌었을 때** — `mrq pull --mr 9` 가 심링크를 갈아
   끼운다. 리뷰 디렉터리를 버퍼 로컬에 캐시하면 옛 MR 의 코멘트를 계속 보여준다
   → **Task 3**
4. **버퍼가 줄어 `location.line` 이 버퍼 밖일 때** — 진단 영역을 만들 때 clamp 하지
   않으면 `flymake-make-diagnostic` 이 범위 밖 위치로 에러를 던지거나 진단이
   사라진다. CLI 는 이 경우를 모른다(디스크 파일만 본다) → **Task 6**
5. **동료가 먼저 resolve 한 스레드** — `review.md`(`review-md.md` §5)와
   `list`(`cli.md` §7)는 서버에서 resolve 됐고 내 미전송 작업이 없는 스레드를
   **감춘다.** `editor.md` §3.1 은 그 규칙을 적지 않았다. 적용하지 않으면 동료가
   코멘트 다섯을 resolve 한 뒤에도 진단이 그대로 떠서, 사람이 보는 세 면이 서로
   다른 집합을 보여준다 (`decisions/0001` 이 막으려는 것) → **Task 6**
6. **`sync` 가 `review.md` 를 다시 쓴 뒤의 point** — 저장 훅이 되읽을 때 줄 번호로
   복원하면 재렌더로 앞 블록 길이가 바뀔 때마다 커서가 흘러간다. 답글을 쓸 때마다
   일어난다 → **Task 8**

---

> **테스트 수에 대하여:** 각 과제의 `Expected:` 에 적힌 `Ran N tests` 는 **기준치**다.
> 실제 수가 다르면 먼저 "테스트 파일이 로드되지 않았나" 를 의심하고
> (`make test` 가 `test/*-test.el` 을 전부 `-l` 로 먹인다), 의도한 차이면 그대로 간다.

## File Structure

| 파일 | 책임 | 과제 |
|---|---|---|
| `plugin_emacs/Makefile` | `test` · `lint` · `deps` · `conformance` | 1 |
| `plugin_emacs/.gitignore` | `.elpa/` · `*.elc` | 1 |
| `plugin_emacs/test/mrq-test-helper.el` | 임시 리포, 가짜 `mrq`, 동기 flymake, watch 대기 | 1·5 |
| `plugin_emacs/mrq-anchor.el` | §6 보정. 의존 0, 부작용 0 | 2 |
| `testdata/conformance/anchor.json` | 적합성 테이블 16건 | 2 |
| `plugin_emacs/mrq-core.el` | 탐색 · json 읽기 · `schema_version` · 캐시 · watch. **유일한 읽기 창구** | 3·4 |
| `plugin_emacs/mrq-cli.el` | `mrq` 실행. **유일한 프로세스 자리** | 5 |
| `plugin_emacs/mrq-flymake.el` | 스레드 → 진단 | 6 |
| `plugin_emacs/mrq-mode.el` | `review.md` 메이저 모드, 키맵, `next-error`, 저장 훅 | 7·8·10 |
| `plugin_emacs/mrq-conflict.el` | `*mrq conflicts*` | 9 |
| `plugin_emacs/mrq.el` | autoload, `mrq-setup`, 패키지 헤더 | 10 |
| `docs/spec/editor.md`, `repo-layout.md` | 규범 반영 | 11 |

---

## Task 1: 스캐폴딩 — `make` 가 빈 ERT 스위트를 돌린다

**Files:**
- Create: `plugin_emacs/Makefile`, `plugin_emacs/.gitignore`,
  `plugin_emacs/mrq-smoke.el`, `plugin_emacs/test/mrq-smoke-test.el`
- Modify: `Makefile` (루트)

**Interfaces:**
- Consumes: 없음
- Produces: `make test-emacs` / `make lint` / `make deps` / `make conformance` 가
  `plugin_emacs/` 로 위임된다. 테스트 러너의 호출 규약:
  `emacs -Q -batch -L . -L test --eval '(setq package-user-dir ".elpa")' -l <each test file> -f ert-run-tests-batch-and-exit`

이 과제의 산출물은 **하네스가 실제로 돈다는 증거**다. `mrq-smoke.el` 과 그 테스트는
Task 2 에서 지운다.

- [ ] **Step 1: 실패하는 테스트**

`plugin_emacs/test/mrq-smoke-test.el`:

```elisp
;;; mrq-smoke-test.el --- 하네스가 도는지 -*- lexical-binding: t -*-
;;; Commentary:
;; Task 2 에서 지운다. 이 파일의 목적은 `make test-emacs` 가 실제로 ERT 를
;; 돌리고 실패를 실패로 보고한다는 것을 한 번 보이는 것이다.
;;; Code:

(require 'mrq-smoke)

(ert-deftest mrq-smoke-harness-runs ()
  (should (equal (mrq-smoke-hello) "mrq")))

(provide 'mrq-smoke-test)
;;; mrq-smoke-test.el ends here
```

- [ ] **Step 2: Makefile 들을 만들고 실패를 관측한다**

`plugin_emacs/.gitignore`:

```
.elpa/
*.elc
```

`plugin_emacs/Makefile`:

```makefile
EMACS      ?= emacs
ELPA       := $(CURDIR)/.elpa
SRC        := $(wildcard *.el)
TESTS      := $(wildcard test/*-test.el)
BATCH      := $(EMACS) -Q -batch --eval '(setq package-user-dir "$(ELPA)")' \
                --eval '(package-initialize)' -L $(CURDIR) -L $(CURDIR)/test

.PHONY: test lint deps conformance clean

deps:
	$(EMACS) -Q -batch \
	  --eval '(setq package-user-dir "$(ELPA)")' \
	  --eval '(require (quote package))' \
	  --eval '(add-to-list (quote package-archives) (cons "melpa" "https://melpa.org/packages/"))' \
	  --eval '(package-initialize)' \
	  --eval '(unless (package-installed-p (quote markdown-mode)) \
	             (package-refresh-contents) (package-install (quote markdown-mode)))'
	@echo "deps -> $(ELPA)"

test:
	@$(BATCH) --eval '(unless (locate-library "markdown-mode") \
	    (message "markdown-mode 가 없습니다 — 먼저 `make deps` 를 실행하세요") (kill-emacs 1))'
	$(BATCH) $(foreach t,$(TESTS),-l $(t)) -f ert-run-tests-batch-and-exit

conformance:
	$(BATCH) -l test/mrq-anchor-test.el \
	  --eval '(ert-run-tests-batch-and-exit "conformance")'

lint:
	$(BATCH) --eval '(setq byte-compile-error-on-warn t)' \
	  -f batch-byte-compile $(SRC)
	$(BATCH) --eval '(progn (require (quote checkdoc)) \
	  (dolist (f (directory-files "$(CURDIR)" t "\\.el\\(quote)")) \
	    (checkdoc-file f)))'
	@$(MAKE) clean

clean:
	rm -f *.elc test/*.elc
```

> **실행자 주의:** `conformance` 타깃은 Task 2 전까지 `test/mrq-anchor-test.el` 이
> 없어 실패한다. Task 1 에서는 `test`·`lint`·`deps` 만 녹색이면 된다.
> `conformance` 는 Task 2 의 Step 6 에서 처음 돌린다.

루트 `Makefile` 의 세 타깃을 바꾼다:

```makefile
test-emacs:
	$(MAKE) -C plugin_emacs test

conformance:
	$(MAKE) -C plugin_emacs conformance

lint:
	cd cli && ruff format --check . && ruff check .
	$(MAKE) -C plugin_emacs lint

deps:
	cd cli && uv sync
	$(MAKE) -C plugin_emacs deps
```

Run: `make -C plugin_emacs deps && make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-smoke`

- [ ] **Step 3: 최소 구현**

`plugin_emacs/mrq-smoke.el`:

```elisp
;;; mrq-smoke.el --- 하네스 확인용 -*- lexical-binding: t -*-
;;; Commentary:
;; Task 2 에서 지운다.
;;; Code:

(defun mrq-smoke-hello ()
  "Return the string \"mrq\"."
  "mrq")

(provide 'mrq-smoke)
;;; mrq-smoke.el ends here
```

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 1 test, 1 result as expected`

Run: `make -C plugin_emacs lint`
Expected: 종료 코드 0, 경고 없음

Run: `make test-emacs` (리포 루트에서)
Expected: 같은 결과 — 위임이 동작한다

- [ ] **Step 5: 격리를 확인한다 (Global Constraint)**

Run: `ls plugin_emacs/.elpa/ && git status --short plugin_emacs/`
Expected: `.elpa/` 안에 `markdown-mode-*` 가 있고, `git status` 에 `.elpa/` 가
나타나지 않는다. `~/.emacs.d/elpa*` 의 mtime 이 바뀌지 않았다

- [ ] **Step 6: Commit**

```bash
git add plugin_emacs/ Makefile
git commit -m "plugin_emacs 스캐폴딩 — make test/lint/deps 가 격리된 .elpa 로 돈다"
```

---

## Task 2: `mrq-anchor.el` 과 적합성 테이블 16건

**Files:**
- Create: `plugin_emacs/mrq-anchor.el`, `plugin_emacs/test/mrq-anchor-test.el`,
  `testdata/conformance/anchor.json`
- Delete: `plugin_emacs/mrq-smoke.el`, `plugin_emacs/test/mrq-smoke-test.el`

**Interfaces:**
- Consumes: 없음 (Emacs 내장만)
- Produces: `(mrq-anchor-correct LINES ANCHOR-LINE LOCATION-LINE)` → 정수.
  `LINES` 는 **1-indexed 로 다루는 문자열 벡터**(인덱스 0 이 1행).
  `ANCHOR-LINE` 이 `nil` 이면 `LOCATION-LINE` 을 그대로 돌려준다

- [ ] **Step 1: 적합성 테이블을 쓴다**

`testdata/conformance/anchor.json` — 순수 JSON(주석 불가). `name` 이 문서다.
필드 의미는 `repo-layout.md` §4.1 (Task 11 이 갱신한다). **전부 1-indexed.**
`buffer_set` 은 `buffer_repeat` 로 만든 버퍼의 `at` 번째 줄을 **치환**한다.

```json
[
  { "name": "유일한 후보를 채택한다",
    "buffer": ["def f():", "    x = 1", "    y = 2"],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 2 },

  { "name": "후보가 둘이면 보정하지 않는다",
    "buffer": ["    x = 1", "", "    x = 1"],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 1 },

  { "name": "완전 일치가 없으면 strip 일치를 쓴다",
    "buffer": ["def f():", "        x = 1"],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 2 },

  { "name": "창(+-200) 밖은 보지 않는다",
    "buffer_repeat": { "line": "pass", "count": 500 },
    "buffer_set": [{ "at": 400, "line": "    x = 1" }],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 1 },

  { "name": "exact 가 둘이면 strip 으로 내려가지 않는다",
    "buffer": ["    x = 1", "pass", "    x = 1", "pass", "        x = 1"],
    "anchor_line": "    x = 1", "location_line": 2, "expect": 2 },

  { "name": "창 경계 +200 은 포함",
    "buffer_repeat": { "line": "pass", "count": 500 },
    "buffer_set": [{ "at": 201, "line": "    x = 1" }],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 201 },

  { "name": "창 경계 +201 은 제외",
    "buffer_repeat": { "line": "pass", "count": 500 },
    "buffer_set": [{ "at": 202, "line": "    x = 1" }],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 1 },

  { "name": "창 경계 -200 은 포함",
    "buffer_repeat": { "line": "pass", "count": 500 },
    "buffer_set": [{ "at": 201, "line": "    x = 1" }],
    "anchor_line": "    x = 1", "location_line": 401, "expect": 201 },

  { "name": "strip 후보가 둘이면 보정하지 않는다",
    "buffer": ["pass", "        x = 1", "pass", "  x = 1"],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 1 },

  { "name": "공백뿐인 앵커는 exact 가 유일하면 채택한다",
    "buffer": ["def f():", "    ", "pass"],
    "anchor_line": "    ", "location_line": 1, "expect": 2 },

  { "name": "공백뿐인 앵커는 strip 단계로 내려가지 않는다",
    "buffer": ["def f():", "        ", "pass"],
    "anchor_line": "  ", "location_line": 1, "expect": 1 },

  { "name": "location_line 이 버퍼보다 커도 창을 clamp 해 탐색한다",
    "buffer": ["pass", "    x = 1", "pass"],
    "anchor_line": "    x = 1", "location_line": 5, "expect": 2 },

  { "name": "창이 버퍼와 겹치지 않으면 보정하지 않는다",
    "buffer": ["pass", "    x = 1", "pass"],
    "anchor_line": "    x = 1", "location_line": 500, "expect": 500 },

  { "name": "앵커가 아예 없으면 보정하지 않는다",
    "buffer": ["def f():", "    y = 2"],
    "anchor_line": "    x = 1", "location_line": 1, "expect": 1 },

  { "name": "빈 버퍼",
    "buffer": [],
    "anchor_line": "    x = 1", "location_line": 3, "expect": 3 },

  { "name": "trailing 공백은 strip 이 흡수한다",
    "buffer": ["def f():", "x = 1   "],
    "anchor_line": "x = 1", "location_line": 1, "expect": 2 }
]
```

> **케이스 5 확인:** 버퍼의 exact 후보는 1행과 3행 둘(`"    x = 1"`), strip-only
> 후보는 5행(`"        x = 1"`). exact 가 2건이므로 strip 단계로 내려가지 않고
> `location_line`(2)을 그대로 쓴다. fold 로 내려갔다면 strip 후보가 3건이 되어
> 역시 보정하지 않겠지만, **이유가 다르다** — 이 케이스는 구현이 2단계에 들어가는지
> 자체를 가른다. 구현이 틀려도 결과가 같아지지 않도록 strip-only 후보를 **하나만**
> 뒀다. 구현이 "exact 둘 → strip 으로 내려감" 이면 strip 후보가 1·3·5 세 개라
> 여전히 2 를 돌려준다 — 그래서 이 케이스만으로는 불충분하다. 케이스 9 가
> 2단계 자체를 덮고, 이 케이스는 설계 의도를 문서로 고정하는 몫이다.

- [ ] **Step 2: 테이블을 돌리는 실패 테스트**

`plugin_emacs/test/mrq-anchor-test.el`:

```elisp
;;; mrq-anchor-test.el --- 적합성 테이블 -*- lexical-binding: t -*-
;;; Commentary:
;; `testdata/conformance/anchor.json` 을 그대로 돌린다 (repo-layout.md §4.1).
;; 세 구현이 어긋나는 것을 막는 유일한 장치이므로, 케이스를 여기에 하드코딩하지
;; 말 것 — 테이블이 정본이다.
;;; Code:

(require 'ert)
(require 'mrq-anchor)

(defconst mrq-anchor-test--table
  (expand-file-name "../../testdata/conformance/anchor.json"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "세 구현이 공유하는 적합성 테이블의 경로.")

(defun mrq-anchor-test--expand (case)
  "CASE 의 버퍼 서술을 문자열 벡터로 펼친다."
  (let ((plain (gethash "buffer" case))
        (repeat (gethash "buffer_repeat" case)))
    (cond
     (repeat
      (let* ((count (gethash "count" repeat))
             (lines (make-vector count (gethash "line" repeat))))
        (dolist (set (append (gethash "buffer_set" case) nil))
          ;; `at` 은 1-indexed
          (aset lines (1- (gethash "at" set)) (gethash "line" set)))
        lines))
     (t (vconcat plain)))))

(ert-deftest mrq-anchor-conformance ()
  "`testdata/conformance/anchor.json` 의 모든 케이스."
  (let ((cases (with-temp-buffer
                 (insert-file-contents mrq-anchor-test--table)
                 (goto-char (point-min))
                 (json-parse-buffer :array-type 'list))))
    (should (= (length cases) 16))
    (dolist (case cases)
      (let* ((name (gethash "name" case))
             (lines (mrq-anchor-test--expand case))
             (got (mrq-anchor-correct lines
                                      (gethash "anchor_line" case)
                                      (gethash "location_line" case)))
             (want (gethash "expect" case)))
        (should (equal (cons name got) (cons name want)))))))

(provide 'mrq-anchor-test)
;;; mrq-anchor-test.el ends here
```

- [ ] **Step 3: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-anchor`

- [ ] **Step 4: 구현**

`plugin_emacs/mrq-anchor.el`:

```elisp
;;; mrq-anchor.el --- 저장 안 된 버퍼의 앵커 보정 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `docs/spec/reanchoring.md' §6 의 범위 그대로다.  에디터가 할 수 있는 보정은
;; 이것뿐이고, 세 구현(Python CLI 는 제외 — §4.1 참고, elisp, TypeScript)이
;; `testdata/conformance/anchor.json' 으로 같게 동작하는 것을 강제당한다.
;;
;; CLI 의 `mrq.search' 와 **일부러 다른 알고리즘**이다.  CLI 는 창 50 + context
;; 점수 + 전체 파일 fallback 을 쓴다.  여기서는 창 200, exact -> strip, 후보가
;; 유일할 때만 채택한다.  창을 넓힌 것은 저장 안 된 버퍼가 세션 중에 많이
;; 움직이기 때문이고, 나머지를 좁힌 것은 세 언어로 복제되는 코드라 어긋날
;; 여지를 줄여야 하기 때문이다.
;;
;; 이 파일은 Emacs 내장 외에 아무것도 require 하지 않는다.  버퍼도 파일도
;; `review.json' 도 모른다.

;;; Code:

(require 'subr-x)

(defconst mrq-anchor-window 200
  "`location.line' 에서 앞뒤로 몇 줄까지 보는가.  `reanchoring.md' §6.")

(defun mrq-anchor-correct (lines anchor-line location-line)
  "LINES 안에서 ANCHOR-LINE 을 찾아 보정된 줄 번호를 돌려준다.

LINES 는 1 행이 인덱스 0 인 문자열 벡터다.  LOCATION-LINE 은 1-indexed
검색 시작점이며, 보정하지 않기로 하면 그대로 돌려준다.

후보가 유일할 때만 채택한다 (MUST).  `anchor.line' 완전 일치를 먼저 보고,
완전 일치가 **한 건도 없을 때만** `string-trim' 일치로 내려간다 — 완전 일치가
여럿이면 더 느슨한 비교로 내려가 봐야 후보가 늘기만 한다.

ANCHOR-LINE 이 공백뿐이면 완전 일치만 본다.  빈 줄 주변은 또 빈 줄이라
trim 비교가 근거를 잃는다 — CLI 의 `mrq.search' 가 같은 결정을 한다."
  (if (or (null anchor-line) (null location-line))
      location-line
    (let* ((total (length lines))
           (lo (max 1 (- location-line mrq-anchor-window)))
           (hi (min total (+ location-line mrq-anchor-window))))
      (if (> lo hi)
          location-line
        (let ((exact (mrq-anchor--matches lines lo hi
                                          (lambda (text) (equal text anchor-line)))))
          (cond
           ((string-empty-p (string-trim anchor-line))
            (if (= (length exact) 1) (car exact) location-line))
           ((= (length exact) 1) (car exact))
           (exact location-line)
           (t
            (let* ((target (string-trim anchor-line))
                   (stripped (mrq-anchor--matches
                              lines lo hi
                              (lambda (text) (equal (string-trim text) target)))))
              (if (= (length stripped) 1) (car stripped) location-line)))))))))

(defun mrq-anchor--matches (lines lo hi predicate)
  "LINES 의 LO..HI(1-indexed, 양끝 포함)에서 PREDICATE 를 만족하는 줄 번호들."
  (let ((found nil)
        (line hi))
    (while (>= line lo)
      (when (funcall predicate (aref lines (1- line)))
        (push line found))
      (setq line (1- line)))
    found))

(provide 'mrq-anchor)
;;; mrq-anchor.el ends here
```

- [ ] **Step 5: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 2 tests, 2 results as expected` (smoke + conformance)

하나라도 실패하면 **케이스 이름이 메시지에 나온다** (`should (equal (cons name got) ...)`
가 그 때문이다).

- [ ] **Step 6: smoke 를 지우고 `make conformance` 를 처음 돌린다**

```bash
rm plugin_emacs/mrq-smoke.el plugin_emacs/test/mrq-smoke-test.el
```

Run: `make -C plugin_emacs test && make conformance && make -C plugin_emacs lint`
Expected: 셋 다 0. `make conformance` 가 `Ran 1 test` 를 찍는다

- [ ] **Step 7: Commit**

```bash
git add plugin_emacs/ testdata/conformance/
git commit -m "mrq-anchor.el 과 적합성 테이블 16건 — 세 구현을 묶는 장치"
```

---

## Task 3: `mrq-core.el` — 탐색, 읽기, `schema_version`

**Files:**
- Create: `plugin_emacs/mrq-core.el`, `plugin_emacs/test/mrq-core-test.el`,
  `plugin_emacs/test/mrq-test-helper.el`
- Create: `plugin_emacs/test/mrq-schema-test.el`

**Interfaces:**
- Consumes: 없음 (Emacs 내장만)
- Produces:
  - `(mrq-core-review-dir &optional FILE)` → 리뷰 디렉터리 절대 경로 또는 `nil`
  - `(mrq-core-root &optional FILE)` → 리포 루트 또는 `nil`
  - `(mrq-core-review DIR)` → 해시테이블(파싱된 `review.json`) 또는 `nil`
  - `(mrq-core-threads-for FILE)` → 그 파일의 스레드 해시테이블 리스트
  - `(defcustom mrq-executable "mrq")`, `(defcustom mrq-show-handled nil)`,
    `(defgroup mrq)`
  - 테스트 헬퍼: `(mrq-test-with-repo (ROOT &key review) BODY...)` 매크로 —
    임시 디렉터리에 `.mrq/<iid>/review.json` + `current` 심링크 + 소스 파일을
    깔고 ROOT 를 바인딩한다

- [ ] **Step 1: 헬퍼를 쓴다**

`plugin_emacs/test/mrq-test-helper.el`:

```elisp
;;; mrq-test-helper.el --- 테스트 픽스처 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `docs/spec/testing.md' §2 의 가짜 `glab' 수법을 그대로 가져온다 — 모킹이
;; 아니라 진짜 프로세스와 진짜 파일을 쓴다.  모킹한 `call-process' 는 stdout 과
;; stderr 의 분리나 종료 코드를 틀리게 흉내 내기 쉽고, 그 둘이 정확히
;; `mrq-cli.el' 이 책임지는 것이다.

;;; Code:

(require 'ert)
(require 'mrq-core)

(defun mrq-test-wait-for (predicate &optional seconds)
  "PREDICATE 가 non-nil 이 될 때까지 최대 SECONDS(기본 3) 기다린다.

`file-notify' 와 flymake 는 둘 다 비동기라 여러 테스트 파일이 이것을 쓴다.
테스트 파일 사이의 로드 순서에 기대지 않도록 헬퍼에 둔다."
  (let ((deadline (+ (float-time) (or seconds 3))))
    (while (and (not (funcall predicate)) (< (float-time) deadline))
      (sit-for 0.05))
    (funcall predicate)))

(defconst mrq-test-data-dir
  (expand-file-name "../../testdata/"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "세 구현이 공유하는 테스트 데이터 디렉터리.")

(defun mrq-test-sample-review ()
  "`testdata/review/rendered.json' 의 내용."
  (with-temp-buffer
    (insert-file-contents (expand-file-name "review/rendered.json" mrq-test-data-dir))
    (buffer-string)))

(defmacro mrq-test-with-repo (spec &rest body)
  "임시 리포를 만들고 SPEC 의 첫 심볼에 루트를 바인딩한 채 BODY 를 실행한다.

SPEC 은 (ROOT &key REVIEW IID FILES SYMLINK) 다.
REVIEW 는 `review.json' 의 문자열 내용 (기본 `mrq-test-sample-review').
IID 는 정수 (기본 1234).
FILES 는 (상대경로 . 내용) 의 alist.
SYMLINK 가 nil 이면 `current' 를 심링크가 아니라 iid 를 담은 일반 파일로 쓴다
\(`data-model.md' §1 이 허용하는 fallback)."
  (declare (indent 1) (debug t))
  (let ((root (car spec))
        (opts (cdr spec)))
    `(let* ((,root (make-temp-file "mrq-test-" t))
            (iid (or ,(plist-get opts :iid) 1234))
            (review-dir (expand-file-name (format ".mrq/%d" iid) ,root)))
       (unwind-protect
           (progn
             (make-directory review-dir t)
             (write-region (or ,(plist-get opts :review) (mrq-test-sample-review))
                           nil (expand-file-name "review.json" review-dir) nil 'quiet)
             (if ,(if (plist-member opts :symlink) (plist-get opts :symlink) t)
                 (make-symbolic-link (format "%d" iid)
                                     (expand-file-name ".mrq/current" ,root))
               (write-region (format "%d\n" iid) nil
                             (expand-file-name ".mrq/current" ,root) nil 'quiet))
             (dolist (entry ,(plist-get opts :files))
               (let ((path (expand-file-name (car entry) ,root)))
                 (make-directory (file-name-directory path) t)
                 (write-region (cdr entry) nil path nil 'quiet)))
             ,@body)
         (mrq-core-forget-all)
         (delete-directory ,root t)))))

(defun mrq-test-write-review (root iid text)
  "ROOT/.mrq/IID/review.json 을 TEXT 로 **원자적으로 교체**한다.

CLI 가 `os.replace' 를 쓰므로(`store.py:179') 테스트도 같은 모양이어야 한다 —
제자리 덮어쓰기로 테스트하면 inode 가 안 바뀌어 파일 watch 의 결함을 놓친다."
  (let* ((dir (expand-file-name (format ".mrq/%d" iid) root))
         (final (expand-file-name "review.json" dir))
         (tmp (expand-file-name ".review.json.tmp" dir)))
    (write-region text nil tmp nil 'quiet)
    (rename-file tmp final t)))

(provide 'mrq-test-helper)
;;; mrq-test-helper.el ends here
```

- [ ] **Step 2: `mrq-core` 의 실패 테스트**

`plugin_emacs/test/mrq-core-test.el`:

```elisp
;;; mrq-core-test.el --- 리뷰 상태 접근 계층 -*- lexical-binding: t -*-
;;; Commentary:
;; `editor.md' §2 (리뷰 디렉터리 찾기), §1-6 (schema_version).
;;; Code:

(require 'ert)
(require 'mrq-core)
(require 'mrq-test-helper)

(ert-deftest mrq-core-finds-review-dir-through-symlink ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let ((file (expand-file-name "src/api/client.py" root)))
      (should (equal (file-truename (mrq-core-review-dir file))
                     (file-truename (expand-file-name ".mrq/1234" root))))
      (should (equal (file-truename (mrq-core-root file))
                     (file-truename root))))))

(ert-deftest mrq-core-finds-review-dir-through-plain-file ()
  "`current' 가 일반 파일이면 내용을 iid 로 읽는다 (`data-model.md' §1)."
  (mrq-test-with-repo (root :symlink nil :files '(("src/api/client.py" . "x\n")))
    (should (equal (file-truename
                    (mrq-core-review-dir (expand-file-name "src/api/client.py" root)))
                   (file-truename (expand-file-name ".mrq/1234" root))))))

(ert-deftest mrq-core-returns-nil-outside-a-review-repo ()
  (let ((dir (make-temp-file "mrq-bare-" t)))
    (unwind-protect
        (should (null (mrq-core-review-dir (expand-file-name "a.py" dir))))
      (delete-directory dir t))))

(ert-deftest mrq-core-does-not-cache-a-failed-lookup ()
  "Review Focus #2 — `.mrq' 가 생기기 전에 연 버퍼가 영원히 죽으면 안 된다."
  (let ((dir (make-temp-file "mrq-late-" t)))
    (unwind-protect
        (let ((file (expand-file-name "a.py" dir)))
          (write-region "x\n" nil file nil 'quiet)
          (with-current-buffer (find-file-noselect file)
            (unwind-protect
                (progn
                  (should (null (mrq-core-review-dir file)))
                  ;; 이제 pull 이 돈 것처럼 .mrq 를 만든다
                  (make-directory (expand-file-name ".mrq/7" dir) t)
                  (write-region (mrq-test-sample-review) nil
                                (expand-file-name ".mrq/7/review.json" dir) nil 'quiet)
                  (make-symbolic-link "7" (expand-file-name ".mrq/current" dir))
                  (should (mrq-core-review-dir file)))
              (kill-buffer))))
      (delete-directory dir t))))

(ert-deftest mrq-core-follows-current-when-it-points-elsewhere ()
  "Review Focus #3 — `pull --mr 9' 가 심링크를 갈아 끼운다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let ((file (expand-file-name "src/api/client.py" root)))
      (should (mrq-core-review-dir file))
      (make-directory (expand-file-name ".mrq/9" root) t)
      (write-region (mrq-test-sample-review) nil
                    (expand-file-name ".mrq/9/review.json" root) nil 'quiet)
      (delete-file (expand-file-name ".mrq/current" root))
      (make-symbolic-link "9" (expand-file-name ".mrq/current" root))
      (should (equal (file-truename (mrq-core-review-dir file))
                     (file-truename (expand-file-name ".mrq/9" root)))))))

(ert-deftest mrq-core-threads-for-filters-by-path ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")
                                     ("src/api/retry.py" . "y\n")))
    (let ((threads (mrq-core-threads-for (expand-file-name "src/api/client.py" root))))
      ;; rendered.json 에서 client.py 를 가리키는 스레드는 셋이다
      (should (= (length threads) 3))
      (dolist (thread threads)
        (should (equal (gethash "path" (gethash "location" thread))
                       "src/api/client.py"))))))

(ert-deftest mrq-core-refuses-an-unknown-schema-version ()
  "§1-6 MUST — 모르는 버전이면 동작을 거부한다."
  (let ((text (replace-regexp-in-string
               "\"schema_version\": 1" "\"schema_version\": 99"
               (mrq-test-sample-review) t t)))
    (mrq-test-with-repo (root :review text :files '(("src/api/client.py" . "x\n")))
      (let ((file (expand-file-name "src/api/client.py" root)))
        (should (null (mrq-core-threads-for file)))
        (should (null (mrq-core-review (mrq-core-review-dir file))))))))

(ert-deftest mrq-core-warns-once-per-unknown-version ()
  "flymake 는 편집 중 반복 호출된다.  매번 경고하면 미니버퍼를 못 쓴다."
  (let ((text (replace-regexp-in-string
               "\"schema_version\": 1" "\"schema_version\": 99"
               (mrq-test-sample-review) t t)))
    (mrq-test-with-repo (root :review text :files '(("src/api/client.py" . "x\n")))
      (let ((file (expand-file-name "src/api/client.py" root))
            (count 0))
        (cl-letf (((symbol-function 'message)
                   (lambda (&rest _) (setq count (1+ count)))))
          (mrq-core-threads-for file)
          (mrq-core-threads-for file)
          (mrq-core-threads-for file))
        (should (= count 1))))))

(provide 'mrq-core-test)
;;; mrq-core-test.el ends here
```

- [ ] **Step 3: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-core`

- [ ] **Step 4: 구현**

`plugin_emacs/mrq-core.el`:

```elisp
;;; mrq-core.el --- 리뷰 상태 접근 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `review.json' 을 읽는 **유일한** 창구다.  다른 모듈에 `json-parse' 가 없는
;; 것이 `editor.md' §1-1 (md 를 파싱하지 않는다)을, 이 파일에 쓰기 함수가 없는
;; 것이 §1-2 (json 을 직접 쓰지 않는다)를 코드 모양으로 보장한다.
;; `mrq-boundary-test.el' 이 그 둘을 테스트로 고정한다.
;;
;; `git' 을 부르지 않는다 (§1-4).  리포 루트는 `.mrq/current' 를 위로 찾아
;; 얻는다 (§2) — 디렉터리 탐색이지 git 호출이 아니고, 리포가 이동해도 동작한다.

;;; Code:

(require 'filenotify)
(require 'subr-x)

(defgroup mrq nil
  "GitLab MR 리뷰 코멘트를 버퍼에서 다룬다."
  :group 'tools
  :prefix "mrq-")

(defcustom mrq-executable "mrq"
  "`mrq' CLI 의 경로.  `repo-layout.md' §5."
  :type 'string
  :group 'mrq)

(defcustom mrq-show-handled nil
  "non-nil 이면 처리한 스레드도 진단으로 띄운다.

기본값이 nil 인 이유는 `editor.md' §3.1 — 120 초 예산에서 보고 싶은 것은
\"남은 것\" 이다."
  :type 'boolean
  :group 'mrq)

(defconst mrq-core-schema-version 1
  "이 플러그인이 읽을 수 있는 `review.json' 의 `schema_version'.")

(defvar mrq-core--cache (make-hash-table :test 'equal)
  "리뷰 디렉터리 -> 파싱된 `review.json'.  무효화는 watch 알림으로만 한다.")

(defvar mrq-core--watches (make-hash-table :test 'equal)
  "리뷰 디렉터리 -> `file-notify' 디스크립터.")

(defvar mrq-core--warned (make-hash-table :test 'equal)
  "경고를 이미 낸 (디렉터리 . 버전) 쌍.")

(defvar-local mrq-core--root nil
  "이 버퍼가 속한 리포 루트.  `current' 와 달리 세션 중에 바뀌지 않는다.")

(defun mrq-core-root (&optional file)
  "FILE(기본 `buffer-file-name')이 속한 리포 루트.  없으면 nil.

성공만 버퍼 로컬에 기억한다.  실패를 기억하면 `mrq pull' 전에 열어 둔 버퍼가
영원히 죽는다 — 탐색은 `file-exists-p' 몇 번이라 매번 해도 싸다."
  (or mrq-core--root
      (let* ((path (or file buffer-file-name))
             (found (and path
                         (locate-dominating-file
                          path
                          (lambda (dir) (file-exists-p (expand-file-name ".mrq/current" dir)))))))
        (when found
          (setq found (expand-file-name found))
          (when (and (buffer-file-name) (equal path (buffer-file-name)))
            (setq mrq-core--root found))
          found))))

(defun mrq-core-review-dir (&optional file)
  "FILE 이 속한 리뷰 디렉터리.  없으면 nil.

`current' 는 **접근할 때마다 다시 푼다** — `mrq pull --mr 9' 가 심링크를 갈아
끼우면 따라가야 한다.  디렉터리를 캐시하면 옛 MR 의 코멘트를 계속 보여준다."
  (let ((root (mrq-core-root file)))
    (when root
      (let ((current (expand-file-name ".mrq/current" root)))
        (cond
         ((file-directory-p current) (file-name-as-directory current))
         ((file-exists-p current)
          (let ((iid (string-trim (with-temp-buffer
                                    (insert-file-contents current)
                                    (buffer-string)))))
            (and (not (string-empty-p iid))
                 (file-name-as-directory
                  (expand-file-name (concat ".mrq/" iid) root))))))))))

(defun mrq-core-review (dir)
  "DIR 의 `review.json' 을 파싱해 돌려준다.  모르는 스키마면 nil.

읽을 때마다 watch 를 보장한다 — 등록이 여기 있는 이유는 `review.json' 이 아직
없을 수도 있기 때문이다(첫 `pull' 전).  watch 는 **디렉터리**에 건다."
  (when dir
    (mrq-core--ensure-watch dir)
    (let ((hit (gethash dir mrq-core--cache 'miss)))
      (if (not (eq hit 'miss))
          hit
        (puthash dir (mrq-core--load dir) mrq-core--cache)))))

(defun mrq-core--load (dir)
  "DIR/review.json 을 읽는다.  실패하거나 스키마를 모르면 nil."
  (let ((path (expand-file-name "review.json" dir)))
    (when (file-readable-p path)
      (let ((parsed (condition-case err
                        (with-temp-buffer
                          (insert-file-contents path)
                          (goto-char (point-min))
                          (json-parse-buffer :array-type 'list))
                      (error
                       (mrq-core--warn-once
                        dir 'unreadable
                        (format "mrq: %s 를 읽을 수 없습니다 — %s"
                                path (error-message-string err)))
                       nil))))
        (when parsed
          (let ((version (gethash "schema_version" parsed)))
            (if (equal version mrq-core-schema-version)
                parsed
              (mrq-core--warn-once
               dir version
               (format (concat "mrq: %s 의 schema_version 이 %s 입니다 "
                               "(이 mrq.el 은 %d). 동작을 거부합니다 — "
                               "mrq.el 또는 mrq CLI 를 업데이트하세요.")
                       path version mrq-core-schema-version))
              nil)))))))

(defun mrq-core--warn-once (dir key text)
  "DIR 과 KEY 의 쌍마다 TEXT 를 한 번만 낸다.

flymake 가 편집 중 반복 호출되므로 매번 내면 미니버퍼를 못 쓴다."
  (let ((seen (cons dir key)))
    (unless (gethash seen mrq-core--warned)
      (puthash seen t mrq-core--warned)
      (message "%s" text)
      (mrq-core--log text))))

(defun mrq-core--log (text)
  "TEXT 를 `*mrq*' 버퍼에 남긴다."
  (with-current-buffer (get-buffer-create "*mrq*")
    (goto-char (point-max))
    (let ((inhibit-read-only t))
      (insert text "\n"))))

(defun mrq-core-threads-for (file)
  "FILE 의 리포 상대 경로를 `location.path' 로 가진 스레드들."
  (let* ((root (mrq-core-root file))
         (review (and root (mrq-core-review (mrq-core-review-dir file)))))
    (when review
      (let ((relative (file-relative-name (expand-file-name file) root))
            (out nil))
        (dolist (thread (gethash "threads" review) (nreverse out))
          (let ((location (gethash "location" thread)))
            (when (and location
                       (not (eq location :null))
                       (equal (gethash "path" location) relative))
              (push thread out))))))))

(defun mrq-core--ensure-watch (dir)
  "DIR 에 `file-notify' watch 를 보장한다.

**파일이 아니라 디렉터리에 건다.**  CLI 가 temp 파일 + `os.replace' 로
`review.json' 을 쓰므로(`store.py:179') inode 가 바뀐다 — 파일에 건 watch 는
첫 쓰기 이후 끊긴 inode 에 남아 조용히 죽는다.  디렉터리 watch 는 그 교체를
`renamed'/`created' 로 보고, 덤으로 첫 `pull' 이 json 을 만드는 순간도 잡는다.

해제하지 않는다 — 상한이 \"이 세션에서 건드린 MR 수\" 라 누수가 아니고,
버퍼 단위로 걸고 풀면 `kill-buffer' 경로가 전부 샌다."
  (unless (gethash dir mrq-core--watches)
    (when (file-directory-p dir)
      (puthash dir
               (file-notify-add-watch
                dir '(change)
                (lambda (event) (mrq-core--on-change dir event)))
               mrq-core--watches))))

(defun mrq-core--on-change (dir event)
  "DIR 의 EVENT 가 `review.json' 에 대한 것이면 캐시를 버리고 진단을 갱신한다."
  (let ((files (cl-remove-if-not #'stringp (cddr event))))
    (when (cl-some (lambda (f) (equal (file-name-nondirectory f) "review.json")) files)
      (mrq-core-refresh dir))))

(defun mrq-core-refresh (dir)
  "DIR 의 캐시를 버리고 그 리포의 열린 버퍼 전체의 flymake 를 다시 돌린다."
  (remhash dir mrq-core--cache)
  (clrhash mrq-core--warned)
  (run-hook-with-args 'mrq-core-refresh-functions dir))

(defvar mrq-core-refresh-functions nil
  "`mrq-core-refresh' 가 부르는 훅.  인자는 리뷰 디렉터리 하나.

`mrq-flymake.el' 이 여기에 붙어 열린 버퍼의 진단을 다시 돌린다.  `mrq-core'
가 flymake 를 직접 부르지 않는 이유는 의존을 한쪽으로만 흘리기 위해서다.")

(defun mrq-core-forget-all ()
  "캐시와 watch 를 전부 버린다.  테스트 정리용."
  (clrhash mrq-core--cache)
  (clrhash mrq-core--warned)
  (maphash (lambda (_ descriptor) (file-notify-rm-watch descriptor)) mrq-core--watches)
  (clrhash mrq-core--watches))

(provide 'mrq-core)
;;; mrq-core.el ends here
```

`cl-remove-if-not`/`cl-some`/`cl-letf` 때문에 `(require 'cl-lib)` 를 상단에 더한다.

- [ ] **Step 5: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 9 tests, 9 results as expected`

- [ ] **Step 6: 스키마 교차 검증 테스트 (`repo-layout.md` §4.2)**

`plugin_emacs/test/mrq-schema-test.el`:

```elisp
;;; mrq-schema-test.el --- testdata/review/*.json 교차 검증 -*- lexical-binding: t -*-
;;; Commentary:
;; `repo-layout.md' §4.2 — 세 구현이 같은 샘플을 읽을 수 있어야 한다.  Emacs 는
;; 최소한 필수 필드와 enum 값을 확인한다.  CLI 가 쓴 것을 에디터가 거부하는
;; 드리프트를 여기서 잡는다.
;;; Code:

(require 'ert)
(require 'mrq-core)
(require 'mrq-test-helper)

(defconst mrq-schema-test--states '("todo" "done" "replied" "skipped"))
(defconst mrq-schema-test--confidences '("exact" "fuzzy" "stale"))

(ert-deftest mrq-schema-every-sample-loads-and-has-required-fields ()
  (let ((samples (directory-files
                  (expand-file-name "review" mrq-test-data-dir) t "\\.json\\'")))
    (should samples)
    (dolist (sample samples)
      (mrq-test-with-repo (root :review (with-temp-buffer
                                          (insert-file-contents sample)
                                          (buffer-string)))
        (let ((review (mrq-core-review (mrq-core-review-dir
                                        (expand-file-name "x.py" root)))))
          (should (cons sample review))
          (dolist (key '("schema_version" "project" "iid" "title" "web_url"
                         "mr_state" "source_branch" "diff_refs" "me"
                         "capabilities" "pulled_at" "threads"))
            (should (cons (list sample key) (gethash key review))))
          (dolist (thread (gethash "threads" review))
            (let ((local (gethash "local" thread))
                  (location (gethash "location" thread)))
              (should (member (gethash "state" local) mrq-schema-test--states))
              (when (and location (not (eq location :null)))
                (should (member (gethash "confidence" location)
                                mrq-schema-test--confidences))))))))))

(provide 'mrq-schema-test)
;;; mrq-schema-test.el ends here
```

> **실행자 주의:** `mrq-test-with-repo` 는 `:files` 를 안 주면 소스 파일을 만들지
> 않는다. 이 테스트는 `review.json` 만 필요하므로 그대로 둔다. `x.py` 는 존재하지
> 않아도 `locate-dominating-file` 이 디렉터리를 거슬러 올라가므로 동작한다.

Run: `make -C plugin_emacs test`
Expected: `Ran 10 tests, 10 results as expected`

- [ ] **Step 7: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-core.el — 탐색, review.json 읽기, schema_version 거부"
```

---

## Task 4: `mrq-core.el` — 캐시와 `file-notify`

**Files:**
- Modify: `plugin_emacs/test/mrq-core-test.el`

**Interfaces:**
- Consumes: Task 3 의 `mrq-core-review`, `mrq-core--ensure-watch`,
  `mrq-core-refresh-functions`, `mrq-test-write-review`
- Produces: 없음 (Task 3 의 구현이 이미 캐시·watch 를 담고 있다. 이 과제는 그것이
  **실제로 동작하는지**를 증명한다)

> **왜 과제를 나누는가:** watch 는 코드를 쓰는 것보다 **그것이 죽지 않는지 보이는
> 것**이 어렵다. Review Focus #1 이 그 함정이고, 한 번만 고쳐 보는 테스트는 통과한다.

- [ ] **Step 1: 실패하는 테스트**

`plugin_emacs/test/mrq-core-test.el` 에 추가:

```elisp
(ert-deftest mrq-core-caches-until-the-file-changes ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let* ((dir (mrq-core-review-dir (expand-file-name "src/api/client.py" root)))
           (first (mrq-core-review dir)))
      (should first)
      ;; 캐시 히트는 같은 객체여야 한다 — 매번 파싱하면 eq 가 깨진다
      (should (eq first (mrq-core-review dir))))))

(ert-deftest mrq-core-notices-two-consecutive-atomic-rewrites ()
  "Review Focus #1 — `os.replace' 는 inode 를 바꾼다.

파일에 건 watch 는 처음 한 번만 알림이 오고 그 뒤로 영영 안 온다.  **두 번**
고쳐야 그 결함이 보인다 — 한 번만 보는 테스트는 통과한다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "x\n")))
    (let* ((file (expand-file-name "src/api/client.py" root))
           (dir (mrq-core-review-dir file))
           (seen 0))
      (let ((mrq-core-refresh-functions
             (list (lambda (_) (setq seen (1+ seen))))))
        (mrq-core-review dir)                      ; watch 등록
        (dotimes (round 2)
          (let ((before seen)
                (text (replace-regexp-in-string
                       "\"title\": \"[^\"]*\""
                       (format "\"title\": \"round %d\"" round)
                       (mrq-test-sample-review) t t)))
            (mrq-test-write-review root 1234 text)
            (should (cons round
                          (mrq-test-wait-for (lambda () (> seen before)))))
            ;; 캐시도 실제로 버려졌는가
            (should (equal (gethash "title" (mrq-core-review dir))
                           (format "round %d" round)))))
        (should (>= seen 2))))))

(ert-deftest mrq-core-watch-catches-a-review-json-created-later ()
  "첫 `pull' 이 json 을 만드는 순간도 디렉터리 watch 가 잡는다."
  (let ((dir (make-temp-file "mrq-empty-" t))
        (seen 0))
    (unwind-protect
        (let ((mrq-core-refresh-functions (list (lambda (_) (setq seen (1+ seen))))))
          (should (null (mrq-core-review dir)))     ; json 이 없다. watch 는 걸린다
          (write-region (mrq-test-sample-review) nil
                        (expand-file-name "review.json" dir) nil 'quiet)
          (should (mrq-test-wait-for (lambda () (> seen 0))))
          (should (mrq-core-review dir)))
      (mrq-core-forget-all)
      (delete-directory dir t))))
```

- [ ] **Step 2: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: 셋 중 최소 하나가 FAIL. 특히 `mrq-core-review` 가 json 이 없을 때
watch 를 거는지, `eq` 로 캐시가 확인되는지가 Task 3 구현의 실제 모양에 달려 있다.

**하나도 실패하지 않으면 멈춰라** — Task 3 의 구현이 이미 옳다는 뜻이지만,
그러면 Review Focus #1 이 증명되지 않은 채 통과한 것이다. 그 경우
`mrq-core--ensure-watch` 를 **일부러 파일 watch로 바꿔**
(`(expand-file-name "review.json" dir)` 를 감시) 두 번째 테스트가 빨개지는지 확인하고,
되돌린 뒤 다음 단계로 간다. 이것이 그 테스트가 실제로 함정을 잡는다는 증거다.

- [ ] **Step 3: 필요한 만큼 고친다**

Task 3 의 `mrq-core--ensure-watch` / `mrq-core-review` / `mrq-core--on-change`
중 테스트가 가리키는 것만 고친다. 새 기능을 더하지 않는다.

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 13 tests, 13 results as expected`

- [ ] **Step 5: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-core 의 watch 가 os.replace 를 두 번 연속으로 따라간다"
```

---

## Task 5: `mrq-cli.el` 과 가짜 `mrq`

**Files:**
- Create: `plugin_emacs/mrq-cli.el`, `plugin_emacs/test/mrq-cli-test.el`
- Modify: `plugin_emacs/test/mrq-test-helper.el` (가짜 `mrq`)

**Interfaces:**
- Consumes: `mrq-core` 의 `mrq-executable`, `mrq-core--log`
- Produces:
  - `(mrq-cli-run ARGS &optional STDIN DIR)` →
    `(:code N :json PARSED-OR-NIL :stderr STRING :stdout STRING)`.
    `ARGS` 는 문자열 리스트. `DIR` 은 `default-directory` (기본 현재 값)
  - 테스트 헬퍼 `(mrq-test-fake-cli ROOT &key code stdout stderr)` → 가짜 `mrq`
    스크립트의 절대 경로. 호출 기록은 `(mrq-test-cli-calls ROOT)` 가
    argv 리스트의 리스트로 돌려준다. stdin 은 `(mrq-test-cli-stdin ROOT)`

- [ ] **Step 1: 가짜 `mrq` 를 헬퍼에 더한다**

`plugin_emacs/test/mrq-test-helper.el` 에 추가:

```elisp
(defun mrq-test-fake-cli (root &rest opts)
  "ROOT 에 가짜 `mrq' 실행 파일을 깔고 그 경로를 돌려준다.

모킹이 아니라 진짜 프로세스다 (`testing.md' §2).  호출될 때마다 argv 를
`calls.txt' 에 한 줄씩, stdin 을 `stdin.txt' 에 덮어쓰고, OPTS 가 지정한
stdout/stderr/종료 코드를 낸다."
  (let ((path (expand-file-name "fake-mrq" root))
        (code (or (plist-get opts :code) 0))
        (stdout (or (plist-get opts :stdout) ""))
        (stderr (or (plist-get opts :stderr) "")))
    (write-region
     (concat "#!/bin/sh\n"
             "printf '%s\\n' \"$*\" >> \"" root "/calls.txt\"\n"
             "cat > \"" root "/stdin.txt\"\n"
             "printf '%s' " (shell-quote-argument stdout) "\n"
             "printf '%s' " (shell-quote-argument stderr) " >&2\n"
             "exit " (number-to-string code) "\n")
     nil path nil 'quiet)
    (set-file-modes path #o755)
    path))

(defun mrq-test-cli-calls (root)
  "가짜 `mrq' 가 받은 호출들.  각 원소는 인자 문자열 하나."
  (let ((log (expand-file-name "calls.txt" root)))
    (when (file-exists-p log)
      (split-string (with-temp-buffer
                      (insert-file-contents log)
                      (buffer-string))
                    "\n" t))))

(defun mrq-test-cli-stdin (root)
  "가짜 `mrq' 가 마지막으로 받은 stdin."
  (let ((path (expand-file-name "stdin.txt" root)))
    (when (file-exists-p path)
      (with-temp-buffer (insert-file-contents path) (buffer-string)))))
```

- [ ] **Step 2: 실패하는 테스트**

`plugin_emacs/test/mrq-cli-test.el`:

```elisp
;;; mrq-cli-test.el --- mrq 프로세스 호출 계층 -*- lexical-binding: t -*-
;;; Commentary:
;; `cli.md' §2 — stdout 은 순수 JSON, 경고·에러는 stderr.  섞으면 파싱이 깨진다.
;;; Code:

(require 'ert)
(require 'mrq-cli)
(require 'mrq-test-helper)

(ert-deftest mrq-cli-separates-stdout-from-stderr ()
  "둘을 섞으면 `--json' 페이로드 파싱이 경고 한 줄에 깨진다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli
                            root
                            :stdout "{\"iid\": 1234, \"applied\": []}"
                            :stderr "review.md:142: 앵커 다음 줄이 헤더가 아님\n"))
           (result (mrq-cli-run '("sync" "--json") nil root)))
      (should (= (plist-get result :code) 0))
      (should (equal (gethash "iid" (plist-get result :json)) 1234))
      (should (string-match-p "review.md:142" (plist-get result :stderr)))
      (should-not (string-match-p "review.md:142" (plist-get result :stdout))))))

(ert-deftest mrq-cli-reports-the-exit-code ()
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli
                            root :code 3
                            :stdout "{\"iid\": 1, \"conflicts\": []}"))
           (result (mrq-cli-run '("sync" "--json") nil root)))
      (should (= (plist-get result :code) 3))
      ;; exit 3 에도 페이로드가 있다 (cli.md §5)
      (should (plist-get result :json)))))

(ert-deftest mrq-cli-leaves-json-nil-when-stdout-is-not-json ()
  "`pull' 처럼 `--json' 이 없는 명령은 평문을 낸다.  깨지면 안 된다."
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli root :stdout "pulled: 15 스레드\n"))
           (result (mrq-cli-run '("pull") nil root)))
      (should (= (plist-get result :code) 0))
      (should (null (plist-get result :json)))
      (should (string-match-p "15" (plist-get result :stdout))))))

(ert-deftest mrq-cli-passes-the-body-on-stdin-not-as-an-argument ()
  "답글 본문을 인자로 넘기지 않는다 (CLAUDE.md, `cli.md' §9)."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (mrq-cli-run '("reply" "a1b2" "-F" "-") "본문에 --force 가 있어도 안전하다" root)
      (should (equal (mrq-test-cli-stdin root) "본문에 --force 가 있어도 안전하다"))
      (should (equal (mrq-test-cli-calls root) '("reply a1b2 -F -"))))))

(ert-deftest mrq-cli-runs-in-the-given-directory ()
  (mrq-test-with-repo (root)
    (let* ((mrq-executable (mrq-test-fake-cli root))
           (default-directory temporary-file-directory))
      (mrq-cli-run '("status" "--json") nil root)
      (should (mrq-test-cli-calls root)))))

(provide 'mrq-cli-test)
;;; mrq-cli-test.el ends here
```

- [ ] **Step 3: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-cli`

- [ ] **Step 4: 구현**

`plugin_emacs/mrq-cli.el`:

```elisp
;;; mrq-cli.el --- mrq 프로세스 호출 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `mrq' 를 띄우는 **유일한** 자리다.
;;
;; stdout 과 stderr 를 반드시 분리한다 — `cli.md' §2 가 "stdout 은 순수 JSON,
;; 경고·에러는 stderr" 를 MUST 로 두는데, 섞으면 경고 한 줄에 페이로드 파싱이
;; 깨진다.  `call-process' 의 (버퍼 stderr-파일) 형태가 그것을 해 준다.
;;
;; 동기 실행이다.  비동기가 필요한 유일한 후보는 `push'(실측 16 초)인데
;; `C-c C-p' 는 확인을 받고 돌리는 명시적 조작이라 블로킹이 맞다.

;;; Code:

(require 'mrq-core)

(defun mrq-cli-run (args &optional stdin dir)
  "`mrq' 를 ARGS 로 실행한다.  STDIN 이 있으면 표준 입력으로 넘긴다.

DIR 은 작업 디렉터리 (기본 `default-directory').  결과는 plist —
:code 종료 코드, :stdout 문자열, :stderr 문자열, :json 파싱된 stdout 또는 nil.

본문을 인자로 넘기지 않는 것이 규약이다 — `mrq reply -F -' 가 그것을 위해 있다."
  (let* ((default-directory (file-name-as-directory (or dir default-directory)))
         (stderr-file (make-temp-file "mrq-stderr-"))
         (stdout "")
         (code nil))
    (unwind-protect
        (with-temp-buffer
          (setq code
                (if stdin
                    (let ((input (make-temp-file "mrq-stdin-")))
                      (unwind-protect
                          (progn
                            (write-region stdin nil input nil 'quiet)
                            (apply #'call-process mrq-executable input
                                   (list (current-buffer) stderr-file) nil args))
                        (delete-file input)))
                  (apply #'call-process mrq-executable nil
                         (list (current-buffer) stderr-file) nil args)))
          (setq stdout (buffer-string)))
      nil)
    (let ((stderr (with-temp-buffer
                    (insert-file-contents stderr-file)
                    (prog1 (buffer-string) (delete-file stderr-file)))))
      (list :code (if (numberp code) code 1)
            :stdout stdout
            :stderr stderr
            :json (mrq-cli--parse stdout)))))

(defun mrq-cli--parse (text)
  "TEXT 가 JSON 객체면 파싱해 돌려준다.  아니면 nil.

`pull'/`open'/`doctor' 처럼 `--json' 이 없는 명령은 평문을 내므로 실패가
정상이다.  여기서 에러를 내면 그 명령들이 전부 깨진다."
  (and (string-match-p "\\`[ \t\n]*{" text)
       (condition-case nil
           (with-temp-buffer
             (insert text)
             (goto-char (point-min))
             (json-parse-buffer :array-type 'list))
         (error nil))))

(provide 'mrq-cli)
;;; mrq-cli.el ends here
```

- [ ] **Step 5: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 18 tests, 18 results as expected`

- [ ] **Step 6: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-cli.el — stdout/stderr 를 분리해 돌려준다"
```

---

## Task 6: `mrq-flymake.el`

**Files:**
- Create: `plugin_emacs/mrq-flymake.el`, `plugin_emacs/test/mrq-flymake-test.el`

### 필터 규칙 — 스펙에 없는 한 줄을 더한다

`editor.md` §3.1 은 진단을 띄우지 않을 조건 셋만 적는다 (`location == null`,
`stale`, 처리된 상태). **네 번째가 빠져 있다** — `review-md.md` §5 와 `cli.md` §7 은
서버에서 resolve 됐고 `local.reply` 가 비어 있고 `state == todo` 인 스레드를
**감춘다.** 적용하지 않으면 동료가 코멘트 다섯을 resolve 한 뒤 `review.md` 와
`mrq list` 에서는 사라진 것이 flymake 에만 남아, 사람과 AI 가 **다른 집합을 본다**
(`decisions/0001-human-and-ai-are-peers.md` 가 막으려는 것).

| 조건 | 동작 |
|---|---|
| `location == null` | 진단 없음 (MUST) |
| `confidence == "stale"` | 진단 없음 (MUST) |
| `location.path` ≠ 이 버퍼의 리포 상대 경로 | 진단 없음 |
| `server.resolved` 이고 `local.reply` 가 비어 있고 `state == todo` | 진단 없음 (`mrq-show-handled` 로 끈다) |
| `local.state != "todo"` | 진단 없음 (SHOULD, `mrq-show-handled` 로 끈다) |
| 위 전부 통과 | `:note` 진단 하나 |

`mrq-show-handled` 가 non-nil 이면 **아래 두 필터를 모두 끈다** — `mrq list --all`
과 같은 집합이다. 위 셋은 MUST 라 끄지 않는다. Task 11 이 이 줄을 §3.1 에 넣는다.

`rendered.json` 의 `src/api/client.py` 스레드 셋이 세 경우를 다 덮는다:

| 스레드 | state | reply | resolved | 기본 | `--all` |
|---|---|---|---|---|---|
| `a1b2c3d4e5f6` | todo | 없음 | 아니오 | **보인다** | 보인다 |
| `d4e5f6a1b2c3` | done | 있음 | 예 | 숨김(처리됨) | 보인다 |
| `e5f6a1b2c3d4` | todo | 없음 | 예 | 숨김(동료가 resolve) | 보인다 |

**기본 1건, `mrq-show-handled` 로 3건.**

**Interfaces:**
- Consumes: `mrq-core-threads-for`, `mrq-core-review-dir`, `mrq-show-handled`,
  `mrq-core-refresh-functions`, `mrq-anchor-correct`
- Produces:
  - `(mrq-flymake-backend REPORT-FN &rest _)` — flymake 백엔드
  - `(mrq-flymake-setup)` — 백엔드를 걸고 `flymake-mode` 를 켠다
  - `(mrq-flymake-thread-at-point &optional POINT)` → thread id 문자열 또는 nil
  - 진단의 `data` 와 overlay property `mrq-thread-id` 에 thread id 가 들어간다

- [ ] **Step 1: 실패하는 테스트**

`plugin_emacs/test/mrq-flymake-test.el`:

```elisp
;;; mrq-flymake-test.el --- flymake 백엔드 -*- lexical-binding: t -*-
;;; Commentary:
;; `editor.md' §3.1 의 필터 규칙과 Review Focus #4 (clamp).
;;; Code:

(require 'ert)
(require 'mrq-flymake)
(require 'mrq-test-helper)

(defun mrq-flymake-test--diagnostics (file)
  "FILE 을 열어 flymake 를 **동기로** 돌리고 진단 리스트를 돌려준다."
  (with-current-buffer (find-file-noselect file)
    (mrq-flymake-setup)
    (let ((done nil))
      (flymake-start nil t)
      (mrq-test-wait-for
       (lambda () (setq done (not (flymake-running-backends)))))
      (should done))
    (prog1 (flymake-diagnostics)
      (kill-buffer))))

;; rendered.json 의 client.py 스레드 셋 (위 표 참고):
;;   a1b2c3d4e5f6  todo  답글없음  미resolve  -> 기본에서 보인다
;;   d4e5f6a1b2c3  done  답글있음  resolve    -> 처리됨이라 숨김
;;   e5f6a1b2c3d4  todo  답글없음  resolve    -> 동료가 resolve 해서 숨김

(ert-deftest mrq-flymake-shows-only-unhandled-by-default ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/client.py" root))))
      (should (= (length diags) 1))
      (should (eq (flymake-diagnostic-type (car diags)) :note))
      (should (equal (flymake-diagnostic-data (car diags)) "a1b2c3d4e5f6")))))

(ert-deftest mrq-flymake-hides-a-thread-a-colleague-resolved ()
  "Review Focus #5 — `review.md' 와 `mrq list' 가 감추는 것을 flymake 도 감춘다.

`e5f6a1b2c3d4' 는 서버에서 resolve 됐고 내 미전송 작업이 없다.  띄우면 사람이
보는 세 면이 서로 다른 집합을 보여준다 (`decisions/0001')."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (let ((ids (mapcar #'flymake-diagnostic-data
                       (mrq-flymake-test--diagnostics
                        (expand-file-name "src/api/client.py" root)))))
      (should-not (member "e5f6a1b2c3d4" ids)))))

(ert-deftest mrq-flymake-keeps-a-resolved-thread-that-has-unsent-work ()
  "`d4e5f6a1b2c3' 는 resolve 됐지만 답글이 남아 있다 — `--all' 집합에는 있어야 한다.

동료가 먼저 resolve 했을 때 내 답글이 조용히 사라지면 안 된다
(`review-md.md' §5 의 예외와 같은 근거)."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (let* ((mrq-show-handled t)
           (ids (mapcar #'flymake-diagnostic-data
                        (mrq-flymake-test--diagnostics
                         (expand-file-name "src/api/client.py" root)))))
      (should (member "d4e5f6a1b2c3" ids)))))

(ert-deftest mrq-flymake-shows-handled-when-asked ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (let* ((mrq-show-handled t)
           (diags (mrq-flymake-test--diagnostics
                   (expand-file-name "src/api/client.py" root))))
      (should (= (length diags) 3)))))

(ert-deftest mrq-flymake-skips-stale-and-locationless-threads ()
  "`editor.md' §3.1 MUST — `stale' 에는 진단을 띄우지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/legacy.py" . "a\nb\n")))
    (should (null (mrq-flymake-test--diagnostics
                   (expand-file-name "src/api/legacy.py" root))))))

(ert-deftest mrq-flymake-marks-fuzzy-in-the-message ()
  (mrq-test-with-repo (root :files '(("src/api/session.py" . "a\nb\nc\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/session.py" root))))
      (should (= (length diags) 1))
      (should (string-match-p "\\[fuzzy\\]" (flymake-diagnostic-text (car diags)))))))

(ert-deftest mrq-flymake-message-starts-with-the-author ()
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\nb\nc\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/retry.py" root))))
      (should (string-match-p "\\`@" (flymake-diagnostic-text (car diags)))))))

(ert-deftest mrq-flymake-carries-the-thread-id ()
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\nb\nc\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/retry.py" root))))
      (should (equal (flymake-diagnostic-data (car diags)) "f6a1b2c3d4e5")))))

(ert-deftest mrq-flymake-clamps-a-line-past-the-end-of-the-buffer ()
  "Review Focus #4 — 버퍼가 줄면 `location.line' 이 버퍼 밖을 가리킨다.

CLI 는 이 경우를 모른다 (디스크 파일만 본다).  clamp 하지 않으면
`flymake-diag-region' 이 nil 을 돌려주고 진단이 조용히 사라지거나 에러가 난다."
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\n")))
    (let ((diags (mrq-flymake-test--diagnostics
                  (expand-file-name "src/api/retry.py" root))))
      (should (= (length diags) 1))
      (should (<= (flymake-diagnostic-end (car diags))
                  (with-current-buffer (find-file-noselect
                                        (expand-file-name "src/api/retry.py" root))
                    (prog1 (point-max) (kill-buffer))))))))

(ert-deftest mrq-flymake-makes-one-diagnostic-per-thread-on-the-same-line ()
  "합치지 않는다 (`editor.md' §3.1)."
  (let ((text (mrq-test-sample-review)))
    ;; retry.py 스레드를 하나 복제해 같은 줄에 둘을 만든다
    (mrq-test-with-repo (root :review (mrq-flymake-test--duplicate-retry text)
                              :files '(("src/api/retry.py" . "a\nb\nc\n")))
      (should (= (length (mrq-flymake-test--diagnostics
                          (expand-file-name "src/api/retry.py" root)))
                 2)))))
```

> **실행자 주의:** `mrq-flymake-test--duplicate-retry` 는 이 파일 안에
> 직접 쓴다 — `json-parse-string` 으로 읽어 `f6a1b2c3d4e5` 스레드를 깊은 복사하고
> `id` 를 `f6a1b2c3d4ff`, `root_note_id` 를 다른 값으로 바꾼 뒤
> `json-serialize` 로 되돌린다. 테스트 파일이므로 `json-parse` 금지 규칙
> (`mrq-boundary-test.el`, Task 10)의 대상이 아니다 — 그 메타 테스트는 `*.el`
> 소스만 본다.

- [ ] **Step 2: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-flymake`

- [ ] **Step 3: 구현**

`plugin_emacs/mrq-flymake.el`:

```elisp
;;; mrq-flymake.el --- MR 코멘트를 flymake 진단으로 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.1.  `flymake-goto-next-error' 가 그대로 "다음 MR 코멘트로
;; 이동" 이 되므로 별도 명령을 만들지 않는다.
;;
;; severity 는 `:note' 다 (MUST) — 컴파일 에러와 섞이면 사용자가 둘을 구별하지
;; 못하고, MR 코멘트가 빌드를 깬 것처럼 보인다.

;;; Code:

(require 'flymake)
(require 'mrq-anchor)
(require 'mrq-core)

(defun mrq-flymake-setup ()
  "이 버퍼에 mrq 백엔드를 걸고 `flymake-mode' 를 켠다."
  (interactive)
  (add-hook 'flymake-diagnostic-functions #'mrq-flymake-backend nil t)
  (add-hook 'mrq-core-refresh-functions #'mrq-flymake--refresh)
  (flymake-mode 1))

(defun mrq-flymake-backend (report-fn &rest _)
  "flymake 백엔드.  REPORT-FN 에 진단 리스트를 넘긴다."
  (funcall report-fn (mrq-flymake--diagnostics (current-buffer))))

(defun mrq-flymake--diagnostics (buffer)
  "BUFFER 의 진단 리스트."
  (with-current-buffer buffer
    (let ((file (buffer-file-name))
          (out nil))
      (when file
        (dolist (thread (mrq-core-threads-for file))
          (let ((diagnostic (mrq-flymake--one buffer thread)))
            (when diagnostic (push diagnostic out)))))
      (nreverse out))))

(defun mrq-flymake--one (buffer thread)
  "THREAD 하나를 BUFFER 의 진단으로.  띄우지 않을 조건이면 nil.

띄우지 않는 네 경우 — `location' 이 없다(MUST), `confidence' 가 `stale'
이다(MUST), 처리된 스레드인데 `mrq-show-handled' 가 nil 이다(SHOULD).
`stale' 을 띄우지 않는 이유는 틀린 위치에 붙은 진단이 위치 신뢰를 잃는
가장 빠른 길이기 때문이다 (`data-model.md' §4.9)."
  (let ((location (gethash "location" thread))
        (local (gethash "local" thread)))
    (when (and location
               (not (eq location :null))
               (not (equal (gethash "confidence" location) "stale"))
               (or mrq-show-handled
                   (and (equal (gethash "state" local) "todo")
                        (mrq-flymake--mine-p thread local))))
      (let* ((line (mrq-flymake--line buffer thread location))
             (end-line (mrq-flymake--end-line location line))
             (region (mrq-flymake--region buffer line end-line)))
        (when region
          (flymake-make-diagnostic
           buffer (car region) (cdr region) :note
           (mrq-flymake--text thread location)
           (gethash "id" thread)
           (list 'mrq-thread-id (gethash "id" thread))))))))

(defun mrq-flymake--mine-p (thread local)
  "THREAD 가 기본 보기에 남아야 하는가.

서버에서 resolve 됐는데 내 미전송 작업이 없으면 아니다 — `review-md.md' §5 와
`cli.md' §7 이 쓰는 것과 같은 규칙이다.  동료가 코멘트를 resolve 한 뒤에도
진단이 남으면 `review.md'/`mrq list' 와 flymake 가 서로 다른 집합을 보여준다
\(`decisions/0001-human-and-ai-are-peers.md')."
  (or (not (eq (gethash "resolved" (gethash "server" thread)) t))
      (not (string-empty-p (string-trim (or (gethash "reply" local) ""))))
      (not (equal (gethash "state" local) "todo"))))

(defun mrq-flymake--line (buffer thread location)
  "LOCATION 의 줄을 BUFFER 안에서 보정한다.

보정은 **저장하지 않은 버퍼에서만** 한다 (`reanchoring.md' §6).  저장된
버퍼의 위치는 CLI 가 git 으로 계산한 값이고, 그쪽이 언제나 더 낫다 — git
diff hunk 맵과 context 점수를 쓸 수 있는 쪽은 CLI 뿐이다."
  (let ((line (gethash "line" location))
        (anchor (gethash "anchor" thread)))
    (with-current-buffer buffer
      (if (or (not (buffer-modified-p)) (null anchor) (eq anchor :null))
          line
        (mrq-anchor-correct (mrq-flymake--buffer-lines)
                            (gethash "line" anchor)
                            line)))))

(defun mrq-flymake--buffer-lines ()
  "현재 버퍼를 1 행이 인덱스 0 인 문자열 벡터로."
  (vconcat (split-string (buffer-substring-no-properties (point-min) (point-max))
                         "\n")))

(defun mrq-flymake--text (thread location)
  "진단 메시지 한 줄.  루트 노트의 첫 줄을 자른다."
  (let* ((notes (gethash "notes" thread))
         (root (car notes))
         (author (and root (gethash "author" root)))
         (body (or (and root (gethash "body" root)) ""))
         (first (car (split-string body "\n")))
         (fuzzy (equal (gethash "confidence" location) "fuzzy")))
    (concat "@" (or author "?") ": "
            (truncate-string-to-width first 70 nil nil "…")
            (if fuzzy " [fuzzy]" ""))))

(defun mrq-flymake--end-line (location line)
  "보정 delta 를 반영한 끝 줄.  `line_end' 가 없으면 LINE."
  (let ((raw (gethash "line" location))
        (end (gethash "line_end" location)))
    (if (and end (not (eq end :null)) (numberp raw))
        (+ end (- line raw))
      line)))

(defun mrq-flymake--region (buffer line end-line)
  "BUFFER 의 LINE..END-LINE 을 (시작 . 끝) 로.  버퍼 범위로 clamp 한다.

Review Focus #4 — 버퍼가 줄면 `location.line' 이 버퍼 밖을 가리킨다.  CLI 는
디스크 파일만 보므로 이 경우를 모른다.  clamp 하지 않으면 진단이 조용히
사라진다."
  (with-current-buffer buffer
    (let* ((last (line-number-at-pos (point-max)))
           (start (max 1 (min line last)))
           (stop (max start (min end-line last))))
      (flymake-diag-region buffer start
                           (and (/= stop start) stop)))))

(defun mrq-flymake-thread-at-point (&optional position)
  "POSITION(기본 `point')의 진단이 가리키는 thread id.  없으면 nil."
  (let ((diagnostics (flymake-diagnostics (or position (point)))))
    (and diagnostics (flymake-diagnostic-data (car diagnostics)))))

(defun mrq-flymake--refresh (dir)
  "DIR 의 리뷰를 보는 열린 버퍼 전체의 flymake 를 다시 돌린다."
  (dolist (buffer (buffer-list))
    (with-current-buffer buffer
      (when (and buffer-file-name
                 (bound-and-true-p flymake-mode)
                 (memq #'mrq-flymake-backend flymake-diagnostic-functions)
                 (equal (mrq-core-review-dir buffer-file-name) dir))
        (flymake-start)))))

(provide 'mrq-flymake)
;;; mrq-flymake.el ends here
```

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 28 tests, 28 results as expected`

- [ ] **Step 5: 보정이 실제로 걸리는지 테스트를 더한다**

```elisp
(ert-deftest mrq-flymake-corrects-the-line-in-a-modified-buffer ()
  "`reanchoring.md' §6 — 저장하지 않은 버퍼에서만 보정한다."
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\nb\nc\nd\n")))
    (let ((file (expand-file-name "src/api/retry.py" root)))
      (with-current-buffer (find-file-noselect file)
        (unwind-protect
            (progn
              ;; retry.py 스레드의 anchor.line 을 버퍼 어딘가에 심고 줄을 민다
              (goto-char (point-min))
              (insert "\n\n")             ; 두 줄 밀림 + buffer-modified-p
              (should (buffer-modified-p))
              (mrq-flymake-setup)
              (flymake-start nil t)
              (mrq-test-wait-for (lambda () (not (flymake-running-backends))))
              (should (flymake-diagnostics)))
          (set-buffer-modified-p nil)
          (kill-buffer))))))

(ert-deftest mrq-flymake-does-not-correct-a-saved-buffer ()
  (mrq-test-with-repo (root :files '(("src/api/retry.py" . "a\nb\nc\nd\n")))
    (let* ((file (expand-file-name "src/api/retry.py" root))
           (diags (mrq-flymake-test--diagnostics file)))
      ;; 저장된 버퍼이므로 CLI 가 준 줄을 그대로 쓴다
      (should diags))))
```

> **실행자 주의:** 이 두 테스트는 `rendered.json` 의 `f6a1b2c3d4e5` 스레드의
> 실제 `anchor.line` 과 `location.line` 값에 달려 있다. 먼저
> `python3 -c "import json;d=json.load(open('testdata/review/rendered.json'));..."`
> 로 그 값을 **읽고**, 버퍼 내용을 그 `anchor.line` 이 정확히 한 번 나오도록
> 만들어라. 값을 추측하지 마라.

Run: `make -C plugin_emacs test`
Expected: `Ran 30 tests, 30 results as expected`

- [ ] **Step 6: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-flymake.el — 스레드를 :note 진단으로, 보정과 clamp 포함"
```

---

## Task 7: `mrq-mode.el` — 정규식, 키맵, `next-error`, `RET`

**Files:**
- Create: `plugin_emacs/mrq-mode.el`, `plugin_emacs/test/mrq-mode-test.el`

**Interfaces:**
- Consumes: `mrq-core-root`, `mrq-core-review-dir`, `mrq-anchor-correct`
- Produces:
  - `(defconst mrq-mode-header-re "^## \\[.\\] \\(.+?\\):\\([0-9]+\\)")`
  - `(define-derived-mode mrq-mode markdown-mode "MRQ")`
  - `(mrq-mode-visit)` — `RET`
  - `(mrq-mode-toggle-state)` — `C-c C-t`
  - `(mrq-mode-next-error N RESET)` — `next-error-function`

- [ ] **Step 1: 실패하는 테스트**

`plugin_emacs/test/mrq-mode-test.el`:

```elisp
;;; mrq-mode-test.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-
;;; Commentary:
;; `editor.md' §3.2, `review-md.md' §3 (헤더 형식).
;; 이 파일만 `markdown-mode' 에 의존한다.
;;; Code:

(require 'ert)
(require 'mrq-mode)
(require 'mrq-test-helper)

(ert-deftest mrq-mode-header-re-matches-a-located-header ()
  (let ((line "## [ ] src/api/client.py:102 — @jdoe"))
    (should (string-match mrq-mode-header-re line))
    (should (equal (match-string 1 line) "src/api/client.py"))
    (should (equal (match-string 2 line) "102"))))

(ert-deftest mrq-mode-header-re-matches-every-state-char ()
  (dolist (char '(" " "x" "~" "-"))
    (should (string-match mrq-mode-header-re
                          (format "## [%s] a/b.py:1 — @x" char)))))

(ert-deftest mrq-mode-header-re-ignores-general-headers ()
  "의도된 동작이다 (`review-md.md' §3) — 위치가 없는 코멘트다."
  (should-not (string-match mrq-mode-header-re "## [ ] (general) — @kim")))

(ert-deftest mrq-mode-header-re-ignores-reply-sections-and-prose ()
  (should-not (string-match mrq-mode-header-re "### reply"))
  (should-not (string-match mrq-mode-header-re "본문에 src/a.py:1 이 있어도"))
  (should-not (string-match mrq-mode-header-re "# !1234 Add retry logic")))

(ert-deftest mrq-mode-header-re-is-the-one-compilation-entry ()
  "정의가 둘로 갈라지면 `M-g n' 과 `RET' 이 다른 데로 간다."
  (require 'compile)
  (should (equal (cadr (assq 'mrq compilation-error-regexp-alist-alist))
                 mrq-mode-header-re)))

(ert-deftest mrq-mode-toggles-the-checkbox-in-a-cycle ()
  "문자 치환일 뿐이다 — 의미는 `sync' 가 준다 (`editor.md' §1)."
  (with-temp-buffer
    (insert "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n"
            "## [ ] src/api/client.py:102 — @jdoe\n"
            "\n### reply\n\n")
    (goto-char (point-min))
    (forward-line 3)                     ; reply 영역 안
    (delay-mode-hooks (mrq-mode))
    (dolist (want '("x" "~" "-" " "))
      (mrq-mode-toggle-state)
      (goto-char (point-min))
      (should (search-forward (format "## [%s] src" want) nil t))
      (goto-char (point-min))
      (forward-line 3))))

(ert-deftest mrq-mode-visit-opens-the-source-relative-to-the-repo-root ()
  "경로는 리포 상대다 — `review.md' 가 있는 `.mrq/<iid>/' 기준이 아니다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\n")))
    (let ((md (expand-file-name ".mrq/1234/review.md" root)))
      (write-region (concat "<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->\n"
                            "## [ ] src/api/client.py:2 — @jdoe\n")
                    nil md nil 'quiet)
      (with-current-buffer (find-file-noselect md)
        (unwind-protect
            (progn
              (delay-mode-hooks (mrq-mode))
              (goto-char (point-min))
              (forward-line 1)
              (mrq-mode-visit)
              (should (equal (file-truename (buffer-file-name))
                             (file-truename (expand-file-name "src/api/client.py" root))))
              (should (= (line-number-at-pos) 2))
              (kill-buffer))
          (when (get-file-buffer md) (kill-buffer (get-file-buffer md))))))))

(ert-deftest mrq-mode-is-the-major-mode-for-a-review-md ()
  (mrq-test-with-repo (root)
    (let ((md (expand-file-name ".mrq/1234/review.md" root)))
      (write-region "# !1234 t\n" nil md nil 'quiet)
      (with-current-buffer (find-file-noselect md)
        (unwind-protect (should (eq major-mode 'mrq-mode))
          (kill-buffer))))))

(ert-deftest mrq-mode-does-not-claim-other-review-md-files ()
  (mrq-test-with-repo (root)
    (let ((other (expand-file-name "docs/review.md" root)))
      (make-directory (expand-file-name "docs" root) t)
      (write-region "# hi\n" nil other nil 'quiet)
      (with-current-buffer (find-file-noselect other)
        (unwind-protect (should-not (eq major-mode 'mrq-mode))
          (kill-buffer))))))

(provide 'mrq-mode-test)
;;; mrq-mode-test.el ends here
```

- [ ] **Step 2: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-mode`

- [ ] **Step 3: 구현**

`plugin_emacs/mrq-mode.el` — 이 과제에서는 §3.2 의 읽기 쪽만 만든다
(저장 훅과 CLI 호출은 Task 8).

```elisp
;;; mrq-mode.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.2.  `review.md' 의 메이저 모드다.
;;
;; 이 파일은 `review.md' 에서 **점을 옮기기 위한 검색**만 한다 — 상태나 답글을
;; 추출하지 않는다.  그 값을 읽는 경로는 `review.json' 하나이고 (`mrq-core'),
;; md -> json 변환은 `mrq sync' 하나다 (`editor.md' §1-1).
;;
;; `C-c C-t' 의 체크박스 순환도 **문자 치환**일 뿐이다.  의미는 `sync' 가 준다.

;;; Code:

(require 'compile)
(require 'markdown-mode)
(require 'mrq-anchor)
(require 'mrq-cli)
(require 'mrq-core)

(defconst mrq-mode-header-re "^## \\[.\\] \\(.+?\\):\\([0-9]+\\)"
  "위치가 있는 스레드 헤더.  `review-md.md' §3.

`(general)' 헤더는 **의도적으로** 매치되지 않는다 — 위치를 못 찾은 것이
아니라 위치가 없는 코멘트이고, 가짜 위치로 점프시키면 안 된다.")

(defconst mrq-mode-anchor-re "^<!-- mrq:\\([0-9a-f]\\{8,\\}\\)\\(?: v:[0-9a-f]\\{6\\}\\)? -->$"
  "스레드 블록의 경계.  `review-md.md' §2 — 앵커는 헤더 **위**에 있다.")

(defconst mrq-mode--state-cycle '(?\s ?x ?~ ?-)
  "`C-c C-t' 의 순환 순서.  `review-md.md' §3 의 상태 문자.")

(defvar mrq-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'mrq-mode-visit)
    (define-key map (kbd "C-c C-t") #'mrq-mode-toggle-state)
    map)
  "`mrq-mode' 의 키맵.  Task 8 이 sync/push/pull/reanchor 를 더한다.")

;;;###autoload
(define-derived-mode mrq-mode markdown-mode "MRQ"
  "`review.md' 를 다루는 메이저 모드."
  (setq-local compilation-error-regexp-alist '(mrq))
  (setq-local next-error-function #'mrq-mode-next-error))

;;;###autoload
(add-to-list 'auto-mode-alist '("/\\.mrq/[^/]+/review\\.md\\'" . mrq-mode))

(add-to-list 'compilation-error-regexp-alist-alist
             (list 'mrq mrq-mode-header-re 1 2))

(defun mrq-mode--repo-root ()
  "`review.md' 가 속한 리포 루트.

`.mrq/<iid>/review.md' 에서 두 단계 위다.  `default-directory' 를 쓰면 안
된다 — 헤더의 경로는 **리포 상대**이고 이 버퍼는 `.mrq/<iid>/' 에 있다."
  (or (mrq-core-root (buffer-file-name))
      (error "리포 루트를 찾을 수 없습니다")))

(defun mrq-mode--header-at-point ()
  "point 가 속한 블록의 헤더에서 (경로 . 줄).  위치 헤더가 아니면 nil."
  (save-excursion
    (beginning-of-line)
    (unless (looking-at mrq-mode-header-re)
      (when (re-search-backward mrq-mode-anchor-re nil t)
        (forward-line 1)))
    (when (looking-at mrq-mode-header-re)
      (cons (match-string-no-properties 1)
            (string-to-number (match-string-no-properties 2))))))

(defun mrq-mode-visit ()
  "point 의 스레드가 가리키는 소스 위치로 이동한다."
  (interactive)
  (let ((target (mrq-mode--header-at-point)))
    (unless target
      (user-error "여기에는 위치가 있는 스레드 헤더가 없습니다"))
    (let ((path (expand-file-name (car target) (mrq-mode--repo-root))))
      (unless (file-exists-p path)
        (user-error "%s 가 없습니다" (car target)))
      (find-file path)
      (goto-char (point-min))
      (forward-line (1- (cdr target))))))

(defun mrq-mode-next-error (n reset)
  "`next-error-function'.  N 개 앞으로, RESET 이면 처음부터."
  (when reset (goto-char (point-min)))
  (let ((step (if (< n 0) -1 1)))
    (dotimes (_ (abs n))
      (forward-line step)
      (if (< step 0)
          (unless (re-search-backward mrq-mode-header-re nil t)
            (user-error "이전 코멘트가 없습니다"))
        (unless (re-search-forward mrq-mode-header-re nil t)
          (user-error "다음 코멘트가 없습니다")))
      (beginning-of-line)))
  (mrq-mode-visit))

(defun mrq-mode-toggle-state ()
  "point 가 속한 블록의 체크박스를 순환시킨다.

`[ ]' -> `[x]' -> `[~]' -> `[-]' -> `[ ]'.  **문자만 바꾼다** — 이 함수는
상태의 의미를 해석하지 않고, 반영은 저장 시 `mrq sync' 가 한다."
  (interactive)
  (save-excursion
    (beginning-of-line)
    (unless (looking-at "^## \\[.\\]")
      (if (re-search-backward mrq-mode-anchor-re nil t)
          (forward-line 1)
        (user-error "스레드 블록 안이 아닙니다")))
    (unless (looking-at "^## \\[\\(.\\)\\]")
      (user-error "스레드 헤더를 찾을 수 없습니다"))
    (let* ((current (string-to-char (match-string 1)))
           (rest (cdr (memq current mrq-mode--state-cycle)))
           (next (or (car rest) (car mrq-mode--state-cycle))))
      (replace-match (char-to-string next) t t nil 1))))

(provide 'mrq-mode)
;;; mrq-mode.el ends here
```

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 39 tests, 39 results as expected`

- [ ] **Step 5: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-mode.el — 헤더 정규식, RET, 체크박스 순환, next-error"
```

---

## Task 8: 저장 훅과 종료 코드 분기

**Files:**
- Modify: `plugin_emacs/mrq-mode.el`, `plugin_emacs/test/mrq-mode-test.el`

**Interfaces:**
- Consumes: `mrq-cli-run`, `mrq-core--log`
- Produces:
  - `(mrq-mode-sync)` `C-c C-s`, `(mrq-mode-push)` `C-c C-p`,
    `(mrq-mode-pull)` `g`, `(mrq-mode-reanchor)` `r`
  - `(mrq-mode--report RESULT)` — 종료 코드별 분기. exit 3 은 Task 9 가 채운다
  - `(mrq-mode--revert-keeping-thread)` — 스레드 id 기준 point 복원

- [ ] **Step 1: 실패하는 테스트**

```elisp
(defun mrq-mode-test--open-md (root text)
  "ROOT 의 review.md 를 TEXT 로 만들고 버퍼를 돌려준다."
  (let ((md (expand-file-name ".mrq/1234/review.md" root)))
    (write-region text nil md nil 'quiet)
    (find-file-noselect md)))

(defconst mrq-mode-test--md
  (concat "<!-- mrq:7a0b1c2d3e4f v:000001 -->\n"
          "## [ ] (general) — @kim\n\n### reply\n\n\n"
          "<!-- mrq:a1b2c3d4e5f6 v:000002 -->\n"
          "## [ ] src/api/client.py:2 — @jdoe\n\n### reply\n\n\n"))

(ert-deftest mrq-mode-save-runs-sync ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli
                           root :stdout "{\"iid\":1234,\"applied\":[],\"warnings\":[],\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}")))
      (with-current-buffer (mrq-mode-test--open-md root mrq-mode-test--md)
        (unwind-protect
            (progn
              (goto-char (point-max))
              (insert "확인했습니다.\n")
              (save-buffer)
              (should (equal (mrq-test-cli-calls root) '("sync --json"))))
          (kill-buffer))))))

(ert-deftest mrq-mode-save-restores-point-by-thread-id-not-line ()
  "Review Focus #5 — `sync' 가 md 를 재렌더한다.

줄 번호로 복원하면 앞 블록의 길이가 바뀔 때마다 커서가 흘러간다.  답글을
쓸 때마다 일어나는 일이다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    ;; sync 가 **첫 블록을 늘려서** 재렌더한 것처럼 꾸민다
    (let* ((rerendered (replace-regexp-in-string
                        "## \\[ \\] (general) — @kim\n"
                        "## [ ] (general) — @kim\n\n> 서버가 덧붙인 줄\n> 또 한 줄\n"
                        mrq-mode-test--md t t))
           (script-stdout "{\"iid\":1234,\"applied\":[],\"warnings\":[],\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}")
           (mrq-executable (mrq-test-fake-cli root :stdout script-stdout)))
      (with-current-buffer (mrq-mode-test--open-md root mrq-mode-test--md)
        (unwind-protect
            (progn
              ;; 둘째 블록(a1b2...)의 reply 로 간다
              (goto-char (point-min))
              (search-forward "<!-- mrq:a1b2c3d4e5f6")
              (search-forward "### reply")
              (forward-line 2)
              (let ((before-line (line-number-at-pos)))
                ;; 저장 중에 sync 가 md 를 바꾼 것처럼 파일을 갈아 끼운다
                (let ((after-save-hook after-save-hook))
                  (add-hook 'after-save-hook
                            (lambda () (write-region rerendered nil (buffer-file-name) nil 'quiet))
                            nil t)
                  (save-buffer))
                ;; 되읽은 뒤 point 가 여전히 a1b2 블록 안이어야 한다
                (should (> (line-number-at-pos) before-line))
                (should (save-excursion
                          (re-search-backward mrq-mode-anchor-re nil t)
                          (equal (match-string 1) "a1b2c3d4e5f6")))))
          (set-buffer-modified-p nil)
          (kill-buffer))))))

(ert-deftest mrq-mode-parse-error-does-not-revert-the-buffer ()
  "exit 2 — CLI 가 아무것도 안 썼고 고칠 내용이 버퍼에 있다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli
                           root :code 2
                           :stdout "{\"errors\":[{\"line\":8,\"message\":\"체크박스 문자 '?' 를 해석할 수 없음\"}]}"
                           :stderr "review.md:8: 체크박스 문자 '?' 를 해석할 수 없음\n")))
      (with-current-buffer (mrq-mode-test--open-md root mrq-mode-test--md)
        (unwind-protect
            (progn
              (goto-char (point-max))
              (insert "내가 쓴 것\n")
              (save-buffer)
              (should (string-match-p "내가 쓴 것" (buffer-string)))
              (with-current-buffer "*mrq*"
                (should (string-match-p "review.md:8:" (buffer-string)))))
          (kill-buffer))))))

(ert-deftest mrq-mode-logs-a-warning-without-a-line-without-inventing-one ()
  "`cli.md' §5 MUST NOT — `review.md:0' 도 1 행도 쓰지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli
                           root
                           :stdout (concat "{\"iid\":1234,\"applied\":[],\"warnings\":"
                                           "[{\"line\":null,\"message\":\"a1b2c3d4: 답글이 있는데 상태가 [ ] 입니다\"}],"
                                           "\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}"))))
      (with-current-buffer (mrq-mode-test--open-md root mrq-mode-test--md)
        (unwind-protect
            (progn
              (save-buffer)
              (with-current-buffer "*mrq*"
                (let ((text (buffer-string)))
                  (should (string-match-p "답글이 있는데" text))
                  (should-not (string-match-p "review.md:0" text))
                  (should-not (string-match-p "review.md:1:" text)))))
          (kill-buffer))))))

(ert-deftest mrq-mode-does-nothing-on-saving-a-source-file ()
  "`editor.md' §3.3 — 소스 저장에는 아무것도 하지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (with-current-buffer (find-file-noselect (expand-file-name "src/api/client.py" root))
        (unwind-protect
            (progn
              (goto-char (point-max))
              (insert "c\n")
              (save-buffer)
              (should (null (mrq-test-cli-calls root))))
          (kill-buffer))))))
```

- [ ] **Step 2: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `mrq-mode-sync` 등이 없고 저장 훅이 안 걸려 있다

- [ ] **Step 3: 구현**

`mrq-mode.el` 에 더한다:

```elisp
(defvar mrq-mode--buffer-name "*mrq*"
  "로그와 점프 가능한 메시지가 모이는 버퍼.")

(define-key mrq-mode-map (kbd "C-c C-s") #'mrq-mode-sync)
(define-key mrq-mode-map (kbd "C-c C-p") #'mrq-mode-push)
(define-key mrq-mode-map (kbd "g") #'mrq-mode-pull)
(define-key mrq-mode-map (kbd "r") #'mrq-mode-reanchor)
```

`define-derived-mode` 본문에 저장 훅을 더한다:

```elisp
  (add-hook 'after-save-hook #'mrq-mode--after-save nil t)
```

그리고:

```elisp
(defun mrq-mode--after-save ()
  "`review.md' 를 저장하면 `mrq sync' 를 돌린다 (`editor.md' §3.3).

소스 파일 저장에는 아무것도 하지 않는다 — 이 훅은 `mrq-mode' 버퍼에만
걸리므로 그 구분이 자동으로 된다."
  (mrq-mode-sync))

(defun mrq-mode-sync ()
  "`mrq sync --json' 을 돌리고 결과에 따라 버퍼를 되읽는다."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("sync" "--json") nil (mrq-mode--repo-root))
                    :revert-on-success t))

(defun mrq-mode-reanchor ()
  "`mrq reanchor --json'.  네트워크를 쓰지 않는다."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("reanchor" "--json") nil (mrq-mode--repo-root))
                    :revert-on-success t))

(defun mrq-mode-pull ()
  "`mrq pull' 후 버퍼를 되읽는다."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("pull") nil (mrq-mode--repo-root))
                    :revert-on-success t))

(defun mrq-mode-push ()
  "`mrq status' 요약을 보여주고 확인을 받은 뒤 `mrq push'."
  (interactive)
  (let ((status (mrq-cli-run '("status" "--json") nil (mrq-mode--repo-root))))
    (unless (= (plist-get status :code) 0)
      (mrq-mode--report status)
      (user-error "status 가 실패했습니다"))
    (when (yes-or-no-p (concat (string-trim (plist-get status :stderr)) "\npush 할까요? "))
      (mrq-mode--report (mrq-cli-run '("push" "--json") nil (mrq-mode--repo-root))
                        :revert-on-success t))))

(cl-defun mrq-mode--report (result &key revert-on-success)
  "RESULT 의 종료 코드에 따라 보고하고, 성공이면 버퍼를 되읽는다.

exit 2(파싱 에러)와 exit 3(충돌)에는 **되읽지 않는다** — CLI 가 아무것도
쓰지 않았고, exit 2 는 고칠 내용이 지금 버퍼에 있다."
  (let ((code (plist-get result :code))
        (payload (plist-get result :json)))
    (cond
     ((= code 0)
      (mrq-mode--log-warnings payload)
      (when revert-on-success (mrq-mode--revert-keeping-thread))
      (message "%s" (mrq-mode--summary result payload)))
     ((= code 2) (mrq-mode--log-errors payload result))
     ((= code 3) (mrq-mode--on-conflict payload))
     (t
      (mrq-mode--log (string-trim (plist-get result :stderr)))
      (user-error "mrq: %s"
                  (car (split-string (string-trim (plist-get result :stderr)) "\n")))))))

(defun mrq-mode--on-conflict (payload)
  "exit 3.  Task 9 가 충돌 버퍼로 교체한다."
  (mrq-mode--log (format "충돌 %d건" (length (gethash "conflicts" payload))))
  (user-error "충돌이 있습니다"))

(defun mrq-mode--summary (result payload)
  "에코 영역 한 줄."
  (if (null payload)
      (or (car (split-string (string-trim (plist-get result :stdout)) "\n")) "완료")
    (let ((applied (gethash "applied" payload))
          (anchors (gethash "anchors" payload))
          (warnings (gethash "warnings" payload)))
      (concat (format "applied %d" (length applied))
              (when anchors
                (format " · exact %s fuzzy %s stale %s"
                        (gethash "exact" anchors) (gethash "fuzzy" anchors)
                        (gethash "stale" anchors)))
              (when (and warnings (> (length warnings) 0))
                (format " · 경고 %d건 (%s)" (length warnings) mrq-mode--buffer-name))))))

(defun mrq-mode--log-warnings (payload)
  "PAYLOAD 의 경고를 `*mrq*' 에 넣는다.

`line' 이 `null' 인 경고에 **위치를 만들어내지 않는다** (`cli.md' §5
MUST NOT).  `review.md:0' 도 1 행도 쓰지 않고 접두사 없는 평문으로 둔다 —
가짜 위치가 위치 신뢰를 잃는 가장 빠른 길이다 (`data-model.md' §4.9)."
  (dolist (warning (and payload (gethash "warnings" payload)))
    (mrq-mode--log (mrq-mode--format-message warning))))

(defun mrq-mode--log-errors (payload result)
  "exit 2 의 에러를 `*mrq*' 에 넣고 거기로 보낸다."
  (dolist (error-item (and payload (gethash "errors" payload)))
    (mrq-mode--log (mrq-mode--format-message error-item)))
  (unless payload
    (mrq-mode--log (string-trim (plist-get result :stderr))))
  (message "파싱 에러 — %s 에서 C-x `" mrq-mode--buffer-name))

(defun mrq-mode--format-message (item)
  "`{line, message}' 를 `review.md:<line>: <message>' 또는 평문으로."
  (let ((line (gethash "line" item))
        (text (gethash "message" item)))
    (if (and line (not (eq line :null)) (numberp line))
        (format "review.md:%d: %s" line text)
      text)))

(defun mrq-mode--log (text)
  "TEXT 를 `*mrq*' 에 넣는다.  그 버퍼는 `compilation-mode' 다.

`default-directory' 를 리뷰 디렉터리로 두면 `review.md:142:' 가 그대로
점프 가능해진다."
  (let ((dir (mrq-core-review-dir (buffer-file-name))))
    (with-current-buffer (get-buffer-create mrq-mode--buffer-name)
      (let ((inhibit-read-only t))
        (unless (derived-mode-p 'compilation-mode)
          (compilation-mode)
          (setq-local compilation-error-regexp-alist '(mrq)))
        (when dir (setq-local default-directory dir))
        (goto-char (point-max))
        (insert text "\n")))))

(defun mrq-mode--thread-at-point ()
  "point 위의 가장 가까운 앵커의 thread id 와 그 블록 안 오프셋."
  (save-excursion
    (let ((here (line-number-at-pos)))
      (beginning-of-line)
      (if (or (looking-at mrq-mode-anchor-re)
              (re-search-backward mrq-mode-anchor-re nil t))
          (cons (match-string-no-properties 1)
                (- here (line-number-at-pos)))
        nil))))

(defun mrq-mode--revert-keeping-thread ()
  "버퍼를 되읽고 point 를 **스레드 id 기준**으로 복원한다.

줄 번호로 복원하면 재렌더로 앞 블록의 줄 수가 바뀔 때마다 커서가 흘러간다 —
답글을 쓸 때마다 일어난다."
  (let ((anchor (mrq-mode--thread-at-point)))
    (revert-buffer t t t)
    (when anchor
      (goto-char (point-min))
      (if (re-search-forward (format "^<!-- mrq:%s " (regexp-quote (car anchor))) nil t)
          (progn (beginning-of-line) (forward-line (cdr anchor)))
        (goto-char (point-min))))))
```

`(require 'cl-lib)` 를 상단에 더한다 (`cl-defun`).

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 44 tests, 44 results as expected`

- [ ] **Step 5: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-mode 의 저장 훅 — sync 후 스레드 id 기준 point 복원"
```

---

## Task 9: `mrq-conflict.el`

**Files:**
- Create: `plugin_emacs/mrq-conflict.el`, `plugin_emacs/test/mrq-conflict-test.el`
- Modify: `plugin_emacs/mrq-mode.el` (`mrq-mode--on-conflict`)

**Interfaces:**
- Consumes: `mrq-cli-run`, `mrq-core-review`, `mrq-core-review-dir`
- Produces:
  - `(mrq-conflict-show PAYLOAD DIR)` — `*mrq conflicts*` 를 띄운다
  - 키: `m` `j` `M` `J` `n` `p` `C-c C-c` `q`
  - `(mrq-conflict--sync-args)` → `("sync" "--json" "--prefer" "a1b2=md" ...)`

> **전 과제가 이 UI 를 결정했다.** 부분 해소는 여전히 전부 실패이므로
> (`data-model.md` §5.3), 키를 누를 때마다 `sync` 를 부르면 **첫 키부터 실패한다.**
> 그래서 `m`/`j` 는 표시만 하고 `C-c C-c` 가 한 번에 보낸다.

- [ ] **Step 1: 실패하는 테스트**

`plugin_emacs/test/mrq-conflict-test.el`:

```elisp
;;; mrq-conflict-test.el --- 충돌 해소 버퍼 -*- lexical-binding: t -*-
;;; Commentary:
;; `editor.md' §3.4, `cli.md' §5 (--prefer [ID=]md|json), `decisions/0013'.
;;; Code:

(require 'ert)
(require 'mrq-conflict)
(require 'mrq-test-helper)

(defconst mrq-conflict-test--payload
  (json-parse-string
   (concat "{\"iid\":1234,\"conflicts\":["
           "{\"thread\":\"a1b2c3d4e5f6\",\"md\":{\"state\":\"done\",\"reply\":\"확인했습니다.\"},"
           " \"json\":{\"state\":\"replied\",\"reply\":\"AI: 상위에서 설정 중입니다.\"}},"
           "{\"thread\":\"b2c3d4e5f6a1\",\"md\":{\"state\":\"skipped\",\"reply\":\"\"},"
           " \"json\":{\"state\":\"replied\",\"reply\":\"AI: 세션 재사용.\"}}]}")
   :array-type 'list)
  "충돌 둘 — 하나는 md, 하나는 json 으로 고를 것이다.")

(ert-deftest mrq-conflict-lists-every-conflict-unchosen ()
  (mrq-test-with-repo (root)
    (mrq-conflict-show mrq-conflict-test--payload (mrq-core-review-dir
                                                   (expand-file-name "x.py" root)))
    (with-current-buffer "*mrq conflicts*"
      (unwind-protect
          (let ((text (buffer-string)))
            (should (string-match-p "a1b2c3d4e5f6" text))
            (should (string-match-p "b2c3d4e5f6a1" text))
            (should (= (how-many "→ ?" (point-min) (point-max)) 2)))
        (kill-buffer)))))

(ert-deftest mrq-conflict-refuses-to-apply-while-anything-is-unchosen ()
  "부분 해소는 CLI 에서 exit 3 이다.  UI 가 그것을 그대로 반영한다."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (mrq-conflict-show mrq-conflict-test--payload
                         (mrq-core-review-dir (expand-file-name "x.py" root)))
      (with-current-buffer "*mrq conflicts*"
        (unwind-protect
            (progn
              (goto-char (point-min))
              (mrq-conflict-choose-md)
              (should-error (mrq-conflict-apply) :type 'user-error)
              (should (null (mrq-test-cli-calls root))))
          (kill-buffer))))))

(ert-deftest mrq-conflict-sends-one-sync-with-every-choice ()
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli
                           root
                           :stdout "{\"iid\":1234,\"applied\":[],\"warnings\":[],\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}")))
      (mrq-conflict-show mrq-conflict-test--payload
                         (mrq-core-review-dir (expand-file-name "x.py" root)))
      (with-current-buffer "*mrq conflicts*"
        (unwind-protect
            (progn
              (goto-char (point-min))
              (mrq-conflict-choose-md)       ; a1b2 → md
              (mrq-conflict-next)
              (mrq-conflict-choose-json)     ; b2c3 → json
              (mrq-conflict-apply)
              (should (equal (mrq-test-cli-calls root)
                             '("sync --json --prefer a1b2c3d4e5f6=md --prefer b2c3d4e5f6a1=json"))))
          (when (get-buffer "*mrq conflicts*") (kill-buffer "*mrq conflicts*")))))))

(ert-deftest mrq-conflict-fill-all-then-override-one ()
  "`M' 로 채우고 개별 `j' 로 덮는다 — CLI 의 스코프 우선 규칙과 같은 모양."
  (mrq-test-with-repo (root)
    (let ((mrq-executable (mrq-test-fake-cli
                           root
                           :stdout "{\"iid\":1234,\"applied\":[],\"warnings\":[],\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}")))
      (mrq-conflict-show mrq-conflict-test--payload
                         (mrq-core-review-dir (expand-file-name "x.py" root)))
      (with-current-buffer "*mrq conflicts*"
        (unwind-protect
            (progn
              (mrq-conflict-choose-all-md)
              (goto-char (point-min))
              (mrq-conflict-next)
              (mrq-conflict-choose-json)
              (mrq-conflict-apply)
              (should (equal (mrq-test-cli-calls root)
                             '("sync --json --prefer a1b2c3d4e5f6=md --prefer b2c3d4e5f6a1=json"))))
          (when (get-buffer "*mrq conflicts*") (kill-buffer "*mrq conflicts*")))))))

(ert-deftest mrq-conflict-shows-both-sides-of-each-thread ()
  "값을 모르면 사용자는 고를 수 없다 (`editor.md' §3.4)."
  (mrq-test-with-repo (root)
    (mrq-conflict-show mrq-conflict-test--payload
                       (mrq-core-review-dir (expand-file-name "x.py" root)))
    (with-current-buffer "*mrq conflicts*"
      (unwind-protect
          (let ((text (buffer-string)))
            (should (string-match-p "확인했습니다\\." text))
            (should (string-match-p "AI: 상위에서 설정 중입니다\\." text))
            (should (string-match-p "done" text))
            (should (string-match-p "replied" text)))
        (kill-buffer)))))

(provide 'mrq-conflict-test)
;;; mrq-conflict-test.el ends here
```

- [ ] **Step 2: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `Cannot open load file: mrq-conflict`

- [ ] **Step 3: 구현**

`plugin_emacs/mrq-conflict.el`:

```elisp
;;; mrq-conflict.el --- 충돌 해소 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.4.  `mrq sync' 의 exit 3 페이로드를 받아 스레드마다 방향을
;; 고르게 한다.
;;
;; **키를 누를 때마다 `sync' 를 부르지 않는다.**  `data-model.md' §5.3 이
;; "충돌이 하나라도 남으면 아무것도 쓰지 않고 exit 3" 을 MUST 로 두므로, 하나씩
;; 보내면 첫 키부터 실패한다.  `m'/`j' 는 표시만 하고 `C-c C-c' 가 모든 선택을
;; 한 번의 호출로 보낸다 — 부분 적용이 불가능하다는 것을 UI 가 그대로 반영한다.
;; 문법과 근거는 `docs/decisions/0013-scoped-conflict-resolution.md'.

;;; Code:

(require 'mrq-cli)
(require 'mrq-core)

(defconst mrq-conflict-buffer-name "*mrq conflicts*"
  "충돌 해소 버퍼의 이름.")

(defvar-local mrq-conflict--entries nil
  "이 버퍼의 충돌들.  각 원소는 (ID STATE . 해시테이블), STATE 는 nil/md/json.")

(defvar-local mrq-conflict--dir nil
  "`mrq sync' 를 돌릴 리뷰 디렉터리.")

(defvar mrq-conflict-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "m") #'mrq-conflict-choose-md)
    (define-key map (kbd "j") #'mrq-conflict-choose-json)
    (define-key map (kbd "M") #'mrq-conflict-choose-all-md)
    (define-key map (kbd "J") #'mrq-conflict-choose-all-json)
    (define-key map (kbd "n") #'mrq-conflict-next)
    (define-key map (kbd "p") #'mrq-conflict-previous)
    (define-key map (kbd "C-c C-c") #'mrq-conflict-apply)
    (define-key map (kbd "q") #'quit-window)
    map)
  "`mrq-conflict-mode' 의 키맵.")

(define-derived-mode mrq-conflict-mode special-mode "MRQ-Conflict"
  "충돌을 스레드마다 해소한다."
  (setq-local truncate-lines nil))

(defun mrq-conflict-show (payload dir)
  "PAYLOAD(`sync --json' 의 exit 3 결과)를 DIR 기준 충돌 버퍼로 띄운다."
  (let ((buffer (get-buffer-create mrq-conflict-buffer-name)))
    (with-current-buffer buffer
      (mrq-conflict-mode)
      (setq mrq-conflict--dir dir)
      (setq mrq-conflict--entries
            (mapcar (lambda (c) (list (gethash "thread" c) nil c))
                    (gethash "conflicts" payload)))
      (mrq-conflict--render))
    (pop-to-buffer buffer)
    buffer))

(defun mrq-conflict--render ()
  "엔트리들을 버퍼에 그린다.  point 는 현재 엔트리에 남는다."
  (let ((index (max 0 (mrq-conflict--index)))
        (inhibit-read-only t))
    (erase-buffer)
    (insert "m: md 채택 · j: json 유지 · M/J: 전체 · C-c C-c: 적용 · q: 닫기\n"
            "선택이 남아 있으면 적용할 수 없습니다 — 부분 해소는 CLI 가 거부합니다.\n\n")
    (dolist (entry mrq-conflict--entries)
      (let* ((id (nth 0 entry))
             (choice (nth 1 entry))
             (conflict (nth 2 entry))
             (md (gethash "md" conflict))
             (json (gethash "json" conflict)))
        (insert (propertize (format "%s" id) 'face 'bold)
                (format "   %s\n"
                        (propertize (pcase choice
                                      ('md "→ md") ('json "→ json") (_ "→ ?"))
                                    'face (if choice 'success 'warning)))
                (format "  md    [%s] %s\n"
                        (gethash "state" md) (mrq-conflict--one-line (gethash "reply" md)))
                (format "  json  [%s] %s\n\n"
                        (gethash "state" json) (mrq-conflict--one-line (gethash "reply" json))))))
    (goto-char (point-min))
    (mrq-conflict--goto index)))

(defun mrq-conflict--one-line (text)
  "TEXT 의 첫 줄.  비어 있으면 빈 문자열."
  (if (or (null text) (string-empty-p text))
      ""
    (car (split-string text "\n"))))

(defconst mrq-conflict--entry-re "^\\([0-9a-f]\\{8,\\}\\)   →"
  "엔트리 머리글.")

(defun mrq-conflict--index ()
  "point 가 속한 엔트리의 0-기반 번호.  없으면 -1."
  (save-excursion
    (beginning-of-line)
    (if (or (looking-at mrq-conflict--entry-re)
            (re-search-backward mrq-conflict--entry-re nil t))
        (let ((id (match-string-no-properties 1))
              (n 0) (found -1))
          (dolist (entry mrq-conflict--entries found)
            (when (equal (nth 0 entry) id) (setq found n))
            (setq n (1+ n))))
      -1)))

(defun mrq-conflict--goto (index)
  "INDEX 번째 엔트리로 point 를 옮긴다."
  (goto-char (point-min))
  (when (re-search-forward mrq-conflict--entry-re nil t (1+ index))
    (beginning-of-line)))

(defun mrq-conflict--choose (direction)
  "현재 엔트리를 DIRECTION 으로 표시한다."
  (let ((index (mrq-conflict--index)))
    (when (< index 0) (user-error "엔트리 위가 아닙니다"))
    (setf (nth 1 (nth index mrq-conflict--entries)) direction)
    (mrq-conflict--render)
    (mrq-conflict--goto index)))

(defun mrq-conflict-choose-md ()
  "현재 스레드를 md 채택으로 표시한다."
  (interactive)
  (mrq-conflict--choose 'md))

(defun mrq-conflict-choose-json ()
  "현재 스레드를 json 유지로 표시한다."
  (interactive)
  (mrq-conflict--choose 'json))

(defun mrq-conflict-choose-all-md ()
  "전부 md 채택으로 채운다.  개별 `m'/`j' 로 덮을 수 있다."
  (interactive)
  (mrq-conflict--choose-all 'md))

(defun mrq-conflict-choose-all-json ()
  "전부 json 유지로 채운다."
  (interactive)
  (mrq-conflict--choose-all 'json))

(defun mrq-conflict--choose-all (direction)
  "모든 엔트리를 DIRECTION 으로."
  (dolist (entry mrq-conflict--entries)
    (setf (nth 1 entry) direction))
  (mrq-conflict--render))

(defun mrq-conflict-next ()
  "다음 엔트리로."
  (interactive)
  (end-of-line)
  (if (re-search-forward mrq-conflict--entry-re nil t)
      (beginning-of-line)
    (user-error "마지막 엔트리입니다")))

(defun mrq-conflict-previous ()
  "이전 엔트리로."
  (interactive)
  (beginning-of-line)
  (if (re-search-backward mrq-conflict--entry-re nil t)
      (beginning-of-line)
    (user-error "첫 엔트리입니다")))

(defun mrq-conflict--sync-args ()
  "선택들을 `mrq sync' 인자 리스트로.

`--prefer <id>=md|json' 을 스레드마다 하나씩.  스코프 없는 형태를 쓰지 않는
이유는 UI 가 모든 충돌에 명시적 선택을 요구하기 때문이다 — 생략하면 사용자가
`M' 로 채운 것인지 빠뜨린 것인지 인자에서 구별되지 않는다."
  (append '("sync" "--json")
          (mapcan (lambda (entry)
                    (list "--prefer"
                          (format "%s=%s" (nth 0 entry) (nth 1 entry))))
                  mrq-conflict--entries)))

(defun mrq-conflict-apply ()
  "모든 선택을 한 번의 `mrq sync' 로 보낸다."
  (interactive)
  (let ((missing (cl-remove-if (lambda (e) (nth 1 e)) mrq-conflict--entries)))
    (when missing
      (mrq-conflict--goto (mrq-conflict--position-of (nth 0 (car missing))))
      (user-error "아직 고르지 않은 스레드가 %d개 있습니다" (length missing))))
  (let ((result (mrq-cli-run (mrq-conflict--sync-args) nil mrq-conflict--dir)))
    (if (= (plist-get result :code) 0)
        (progn
          (message "충돌 %d건을 해소했습니다" (length mrq-conflict--entries))
          (quit-window t))
      (message "mrq sync 실패 (exit %d): %s"
               (plist-get result :code)
               (car (split-string (string-trim (plist-get result :stderr)) "\n"))))))

(defun mrq-conflict--position-of (id)
  "ID 엔트리의 0-기반 번호."
  (let ((n 0) (found 0))
    (dolist (entry mrq-conflict--entries found)
      (when (equal (nth 0 entry) id) (setq found n))
      (setq n (1+ n)))))

(provide 'mrq-conflict)
;;; mrq-conflict.el ends here
```

`(require 'cl-lib)` 를 상단에 더한다.

`mrq-mode.el` 의 `mrq-mode--on-conflict` 를 바꾼다:

```elisp
(defun mrq-mode--on-conflict (payload)
  "exit 3 — 충돌 버퍼를 띄운다.  버퍼는 되읽지 않는다 (CLI 가 아무것도 안 썼다)."
  (require 'mrq-conflict)
  (mrq-conflict-show payload (mrq-core-review-dir (buffer-file-name))))
```

- [ ] **Step 4: 통과를 관측한다**

Run: `make -C plugin_emacs test`
Expected: `Ran 49 tests, 49 results as expected`

- [ ] **Step 5: Commit**

```bash
make -C plugin_emacs lint
git add plugin_emacs/
git commit -m "mrq-conflict.el — 선택을 모아 한 번의 sync 로 보낸다"
```

---

## Task 10: `mrq.el`, `mrq-reply-at-point`, 경계 메타 테스트

**Files:**
- Create: `plugin_emacs/mrq.el`, `plugin_emacs/test/mrq-boundary-test.el`
- Modify: `plugin_emacs/mrq-mode.el` (`mrq-reply-at-point`),
  `plugin_emacs/test/mrq-mode-test.el`

**Interfaces:**
- Consumes: 전부
- Produces:
  - `(mrq-setup)` — 소스 버퍼에서 부른다. flymake 백엔드 + `C-c m` 키맵
  - `(mrq-reply-at-point)` — `C-c m r`
  - `mrq.el` 의 autoload 쿠키와 `Package-Requires`

- [ ] **Step 1: 경계 메타 테스트를 쓴다**

`plugin_emacs/test/mrq-boundary-test.el`:

```elisp
;;; mrq-boundary-test.el --- editor.md §1 을 코드 모양으로 고정 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §1 의 경계는 문장이라 코드가 조용히 벗어날 수 있다.  두 가지를
;; grep 수준에서 강제한다 —
;;
;;   §1-1  `review.json' 을 파싱하는 코드는 `mrq-core.el' 에만 있다
;;   §1-2  `mrq-core.el' 에 쓰기 함수가 없다
;;   §1-4  어디에도 git 호출이 없다
;;
;; 약한 테스트지만, 이 경계를 깨는 변경은 거의 항상 이 패턴으로 나타난다.

;;; Code:

(require 'ert)

(defconst mrq-boundary-test--src-dir
  (expand-file-name ".." (file-name-directory (or load-file-name buffer-file-name)))
  "`plugin_emacs/' 자신.")

(defun mrq-boundary-test--sources ()
  "`plugin_emacs/*.el' 전부."
  (directory-files mrq-boundary-test--src-dir t "\\.el\\'"))

(defun mrq-boundary-test--content (path)
  (with-temp-buffer (insert-file-contents path) (buffer-string)))

(ert-deftest mrq-boundary-only-core-parses-json ()
  "§1-1 — json 을 읽는 코드가 한 곳이면 `review.md' 파서가 생길 자리가 없다."
  (dolist (path (mrq-boundary-test--sources))
    (unless (equal (file-name-nondirectory path) "mrq-core.el")
      (should (cons (file-name-nondirectory path)
                    (not (string-match-p "json-parse\\|json-read"
                                         (mrq-boundary-test--content path))))))))

(ert-deftest mrq-boundary-core-never-writes ()
  "§1-2 — 상태 변경은 `mrq reply'/`state'/`sync' 로만."
  (let ((text (mrq-boundary-test--content
               (expand-file-name "mrq-core.el" mrq-boundary-test--src-dir))))
    (dolist (forbidden '("write-region" "with-temp-file" "delete-file" "rename-file"))
      (should (cons forbidden (not (string-match-p (regexp-quote forbidden) text)))))))

(ert-deftest mrq-boundary-nothing-calls-git ()
  "§1-4 MUST NOT — git 도 네트워크도 부르지 않는다."
  (dolist (path (mrq-boundary-test--sources))
    (let ((text (mrq-boundary-test--content path)))
      (should (cons (file-name-nondirectory path)
                    (not (string-match-p "\"git\"\\|url-retrieve\\|\\bmagit-"
                                         text)))))))

(ert-deftest mrq-boundary-only-cli-spawns-processes ()
  "프로세스를 띄우는 자리가 하나여야 `mrq-executable' 설정이 의미가 있다."
  (dolist (path (mrq-boundary-test--sources))
    (unless (equal (file-name-nondirectory path) "mrq-cli.el")
      (should (cons (file-name-nondirectory path)
                    (not (string-match-p "call-process\\|start-process\\|shell-command"
                                         (mrq-boundary-test--content path))))))))

(provide 'mrq-boundary-test)
;;; mrq-boundary-test.el ends here
```

- [ ] **Step 2: `mrq-reply-at-point` 의 테스트**

`plugin_emacs/test/mrq-mode-test.el` 에 추가:

```elisp
(ert-deftest mrq-reply-at-point-jumps-to-the-reply-section ()
  "소스 ↔ 목록 왕복을 닫는 한 수.

`review.md' 에서 앵커를 **검색**하는 것은 파싱이 아니다 — 상태나 답글을
추출하지 않고 점만 옮긴다 (`editor.md' §1)."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (write-region mrq-mode-test--md nil
                  (expand-file-name ".mrq/1234/review.md" root) nil 'quiet)
    (let ((file (expand-file-name "src/api/client.py" root)))
      (with-current-buffer (find-file-noselect file)
        (unwind-protect
            (progn
              (mrq-setup)
              (flymake-start nil t)
              (mrq-test-wait-for (lambda () (not (flymake-running-backends))))
              (goto-char (point-min))
              (forward-line (1- (line-number-at-pos
                                 (flymake-diagnostic-beg (car (flymake-diagnostics))))))
              (mrq-reply-at-point)
              (should (equal (file-name-nondirectory (buffer-file-name)) "review.md"))
              (should (save-excursion
                        (re-search-backward mrq-mode-anchor-re nil t)
                        (equal (match-string 1) "a1b2c3d4e5f6")))
              (should (save-excursion
                        (forward-line -1)
                        (looking-at "### reply"))))
          (dolist (name '("client.py" "review.md"))
            (dolist (buffer (buffer-list))
              (when (and (buffer-file-name buffer)
                         (equal (file-name-nondirectory (buffer-file-name buffer)) name))
                (kill-buffer buffer)))))))))

(ert-deftest mrq-reply-at-point-errors-without-a-diagnostic ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\n")))
    (with-current-buffer (find-file-noselect (expand-file-name "src/api/client.py" root))
      (unwind-protect
          (should-error (mrq-reply-at-point) :type 'user-error)
        (kill-buffer)))))
```

- [ ] **Step 3: 실패를 관측한다**

Run: `make -C plugin_emacs test`
Expected: FAIL — `mrq-setup` 과 `mrq-reply-at-point` 가 없다

- [ ] **Step 4: 구현**

`plugin_emacs/mrq.el`:

```elisp
;;; mrq.el --- GitLab MR 리뷰 코멘트를 버퍼에서 -*- lexical-binding: t -*-

;; Author: mrq contributors
;; Version: 0.1.0
;; Package-Requires: ((emacs "29.1") (markdown-mode "2.5"))
;; Keywords: tools, vc
;; URL: https://github.com/jngbng/mrq

;;; Commentary:
;;
;; `mrq' CLI 가 내려받은 MR 코멘트를 소스 버퍼의 flymake 진단으로 띄우고,
;; `review.md' 에서 답글을 쓰고, 저장하면 `mrq sync' 를 돌린다.
;;
;; 설정 예:
;;
;;   (use-package mrq
;;     :load-path "~/workspace/mrq/plugin_emacs"
;;     :hook (prog-mode . mrq-setup))
;;
;; `mrq-setup' 은 `.mrq/current' 를 못 찾으면 조용히 빠지므로 `prog-mode-hook'
;; 에 걸어도 안전하다.
;;
;; 이 파일은 진입점이다.  나머지는 `mrq-setup' 이 필요할 때 끌어온다 —
;; 로드 시점에 `markdown-mode' 까지 당겨오지 않기 위해서다.

;;; Code:

(require 'mrq-core)

;;;###autoload
(defun mrq-setup ()
  "이 버퍼에 mrq 를 켠다.  리뷰가 없는 리포면 아무것도 하지 않는다."
  (interactive)
  (when (mrq-core-review-dir (buffer-file-name))
    (require 'mrq-flymake)
    (require 'mrq-mode)
    (mrq-flymake-setup)
    (local-set-key (kbd "C-c m r") #'mrq-reply-at-point)))

(provide 'mrq)
;;; mrq.el ends here
```

`mrq-mode.el` 에 더한다:

```elisp
;;;###autoload
(defun mrq-reply-at-point ()
  "point 의 진단이 가리키는 스레드의 `### reply' 로 점프한다.

`review.md' 에서 **점을 옮기기 위한 검색**은 파싱이 아니다 (`editor.md' §1) —
상태나 답글을 추출하지 않고, 틀려야 커서가 엉뚱한 데 가며 사용자가 즉시 본다.
md 에서 값을 읽는 경로는 없고, md -> json 변환은 `mrq sync' 하나다."
  (interactive)
  (require 'mrq-flymake)
  (let ((id (mrq-flymake-thread-at-point)))
    (unless id
      (user-error "여기에 MR 코멘트가 없습니다"))
    (let* ((dir (mrq-core-review-dir (buffer-file-name)))
           (md (and dir (expand-file-name "review.md" dir))))
      (unless (and md (file-exists-p md))
        (user-error "review.md 가 없습니다 — `mrq pull --render' 로 복원하세요"))
      (pop-to-buffer (find-file-noselect md))
      (goto-char (point-min))
      (unless (re-search-forward (format "^<!-- mrq:%s " (regexp-quote id)) nil t)
        (user-error "%s 의 블록이 review.md 에 없습니다" id))
      (if (re-search-forward "^### reply$" nil t)
          (progn (forward-line 1)
                 (when (looking-at "^$") (forward-line 1)))
        (goto-char (line-beginning-position))))))
```

- [ ] **Step 5: 통과를 관측한다**

Run: `make -C plugin_emacs test && make -C plugin_emacs lint`
Expected: `Ran 55 tests, 55 results as expected`, lint 0

경계 테스트 넷 중 하나라도 빨가면 **그 파일을 고쳐라** — 테스트를 완화하지 마라.

- [ ] **Step 6: Commit**

```bash
git add plugin_emacs/
git commit -m "mrq.el 진입점, mrq-reply-at-point, 경계 메타 테스트"
```

---

## Task 11: 스펙 반영과 실측 체크리스트

**Files:**
- Modify: `docs/spec/editor.md` (§1, §3.1, §3.2, §3.4, §3.5)
- Modify: `docs/spec/repo-layout.md` (§4.1, §4.2)
- Modify: `docs/plans/README.md`
- Modify: `CLAUDE.md` (함정 한 줄)
- Create: `docs/plans/2026-10-14-plugin-emacs-dogfood.md`
- Delete: `docs/plans/2026-10-14-plugin-emacs-design.md`,
  `docs/plans/2026-10-14-plugin-emacs.md`,
  `docs/plans/2026-10-14-pre-step4-prefer-scope.md`

**Interfaces:** 없음

- [ ] **Step 1: `editor.md` §1 에 경계 문장을 넣는다**

§1 의 일곱 줄 뒤, "5번은 사람과 AI가…" 문단 앞에:

```markdown
**1번의 경계.** `review.md` 에서 **점(point)을 옮기기 위한 검색**은 파싱이 아니다.
금지되는 것은 md 에서 `local.state` / `local.reply` 를 **추출하는 것**이다 — 그 값을
읽는 경로는 `review.json` 하나이고, md → json 변환은 `mrq sync` 하나다.

그 경계가 실제로 묶는 것 둘:

- 체크박스 토글(§3.2 `C-c C-t`)은 **버퍼 텍스트만 고치고** 상태를 자기가 해석하지
  않는다. `[ ]→[x]→[~]→[-]` 순환은 문자 치환이고 의미는 `sync` 가 준다
- `g`/`r` 뒤의 버퍼 되읽기는 md 를 다시 읽는 게 아니라 `revert-buffer` 다
```

- [ ] **Step 2: `editor.md` §1-3 에 호출부 규범 네 줄**

3번 항목 아래에 들여써서:

```markdown
   보정을 **부르는 쪽**의 규범 넷:
   1. `buffer-modified-p` 가 nil 이면 보정을 건너뛴다 — §6 의 범위가
      "저장하지 않은 버퍼" 다. 저장된 버퍼의 위치는 CLI 가 git 으로 계산한 값이고
      그쪽이 언제나 더 낫다
   2. 보정이 `d` 줄 옮기면 `location.line_end` 에도 같은 `d` 를 더한다 — 멀티라인
      코멘트의 span 을 잃지 않는다
   3. 진단을 만들 때 **버퍼 범위로 clamp** 한다. 버퍼가 줄면 `location.line` 이
      버퍼 밖을 가리키는데 CLI 는 디스크 파일만 보므로 그 경우를 모른다
   4. `location` 이 `null` 이거나 `confidence == "stale"` 이면 진단 자체가 없으므로
      보정을 부르지 않는다
```

- [ ] **Step 3: `editor.md` §3.1·§3.2 를 구현과 맞춘다**

§3.1 의 마지막 불릿을 고친다:

```markdown
- **`review.json` 이 아니라 그 디렉터리에 `file-notify-add-watch` 를 건다**(MUST).
  CLI 가 temp 파일 + `os.replace` 로 쓰므로 inode 가 바뀌고, 파일에 건 watch 는
  **첫 쓰기 이후 조용히 죽는다** — 처음 한 번은 알림이 오고 그 뒤로 영영 안 온다.
  디렉터리 watch 는 그 교체를 잡고, 덤으로 첫 `pull` 이 json 을 만드는 순간도 잡는다.
  테스트는 **두 번 이상 연속으로** 고쳐야 이 결함을 본다
```

§3.1 의 "기본적으로 `local.state == \"todo\"`만 표시한다" 불릿 **아래**에
한 줄을 더한다:

```markdown
- **서버에서 resolve 됐고 미전송 작업이 없는 스레드는 표시하지 않는다**
  (`review-md.md` §5 와 같은 규칙). `mrq-show-handled` 가 이 필터와 위의 상태
  필터를 함께 끈다 — `mrq list --all` 과 같은 집합이 된다. 이 규칙이 없으면
  동료가 코멘트를 resolve 한 뒤 `review.md`·`mrq list` 에서는 사라진 것이
  flymake 에만 남아, 사람과 AI 가 다른 집합을 본다
  (`decisions/0001-human-and-ai-are-peers.md`)
```

§3.2 의 코드 블록 아래에 더한다:

```markdown
헤더 정규식은 **상수 하나**로 두고 `next-error` 와 `RET` 이 함께 쓴다 — 정의가
둘로 갈라지면 `M-g n` 과 `RET` 이 다른 데로 간다.

경로가 **리포 상대**인 것이 함정이다. `review.md` 는 `.mrq/<iid>/` 에 있으므로
`default-directory` 기준으로 풀면 틀린다. 리포 루트 기준으로 직접 해석한다.

저장 훅은 `sync` 뒤에 버퍼를 되읽어야 하고(`sync` 가 md 를 다시 쓴다),
**point 는 줄 번호가 아니라 스레드 id 로 복원한다**(SHOULD) — 재렌더로 앞 블록의
줄 수가 바뀌면 줄 번호 복원은 커서를 흘려보낸다. 답글을 쓸 때마다 일어난다.
```

- [ ] **Step 4: `editor.md` §3.4 의 충돌 UI 를 다시 쓴다**

"**exit 3 (충돌)**" 문단을 통째로 바꾼다:

```markdown
**exit 3 (충돌)**: `*mrq conflicts*` 버퍼에 스레드별로 md 쪽 값과 json 쪽 값을
나란히 보여준다. `m`(md 채택) / `j`(json 유지) 는 **선택을 표시만** 하고,
`M`/`J` 가 전체를 한 방향으로 채우며(개별 키로 덮는다), `C-c C-c` 가 모든 선택을
**한 번의 `mrq sync --prefer <id>=md|json ...`** 로 보낸다.

**키를 누를 때마다 `sync` 를 부르면 안 된다**(MUST NOT). `data-model.md` §5.3 이
"충돌이 하나라도 남으면 아무것도 쓰지 않고 exit 3" 을 MUST 로 두므로 첫 키부터
실패한다. 고르지 않은 스레드가 남아 있으면 `C-c C-c` 는 거부하고 그리로 point 를
옮긴다 — 부분 적용이 불가능하다는 것을 UI 가 그대로 반영한다.

문법과 근거는 [0013](../decisions/0013-scoped-conflict-resolution.md).

이 UI가 없으면 충돌을 보여줄 수는 있어도 **해소할 방법이 없다** — 사용자가 md를
수동으로 되돌리는 수밖에 없고, json 값을 모르면 그것도 불가능하다.
```

- [ ] **Step 5: `editor.md` §3.5 를 실제 테스트 파일과 맞춘다**

```markdown
### 3.5 테스트

ERT로 검증한다. `make test-emacs` 가 `plugin_emacs/test/*-test.el` 전부를
`emacs -Q -batch` 로 돌린다. `markdown-mode` 는 `plugin_emacs/.elpa/` 에만
설치한다(MUST) — 사용자의 `~/.emacs.d` 를 건드리지 않는다.

| 파일 | 덮는 것 |
|---|---|
| `mrq-anchor-test.el` | `testdata/conformance/anchor.json` 16건 |
| `mrq-core-test.el` | 탐색, 캐시, watch 두 번 연속, `schema_version` 거부 |
| `mrq-schema-test.el` | `testdata/review/*.json` 교차 검증 (`repo-layout.md` §4.2) |
| `mrq-flymake-test.el` | §3.1 의 필터, 보정, clamp, 같은 줄 중복 |
| `mrq-cli-test.el` | stdout/stderr 분리, 종료 코드, stdin |
| `mrq-conflict-test.el` | 표시·전체채움·미선택 거부·인자 조립 |
| `mrq-mode-test.el` | 헤더 정규식, 체크박스 순환, `RET`, 저장 훅의 point 복원 |
| `mrq-boundary-test.el` | §1 의 경계를 코드 모양으로 (json 파싱·쓰기·git·프로세스의 위치) |

`make lint` 는 `byte-compile-error-on-warn t` 로 바이트컴파일하고 `checkdoc` 를
돌린다. elisp 에서 가장 싼 방어다.

CLI 경로는 `mrq-executable`(defcustom, 기본 `"mrq"`)로 찾는다.
```

- [ ] **Step 6: `repo-layout.md` §4.1 의 포맷과 MUST 범위**

예시 JSON 을 실제 테이블의 처음 네 건으로 바꾸고, 필드 표를 갱신한다:

```markdown
| 필드 | 의미 |
|---|---|
| `name` | 케이스 설명. 실패 메시지에 그대로 나온다 |
| `buffer` | 버퍼 내용. **1-indexed** 줄 배열 |
| `buffer_repeat` | `{line, count}` — 큰 버퍼를 json 에 펼치지 않고 생성. `buffer` 와 배타적 |
| `buffer_set` | `[{at, line}]` — `at` 번째 줄을 **치환**한다. 길이는 `count` 그대로이고 순서에 무관하다. `buffer_repeat` 와만 함께 쓴다 |
| `anchor_line` | `anchor.line` 값 |
| `location_line` | `location.line` 값 (검색 시작점) |
| `expect` | 기대 줄 번호. 보정하지 않으면 `location_line` 과 같다 |

**줄 번호는 전부 1-indexed 다.**
```

그리고 MUST 의 범위를 좁힌다:

```markdown
`testdata/conformance/anchor.json`을 **앵커 보정을 구현하는 모든 구현이 읽어 같은
테이블을 돌린다**(MUST). 지금은 `plugin_emacs` 와 `plugin_vscode` 둘이다.

CLI 는 돌리지 않는다 — 저장하지 않은 버퍼가 없고(항상 디스크 파일을 읽는다),
그 경로는 `mrq.search` 가 담당하는 **다른 알고리즘**(창 50 + context 점수 + 전체
파일 fallback)이다. 테이블을 돌리려고 CLI 에 production 호출자가 없는 §6 함수를
넣으면 `search.py` 옆에서 실제로 혼동을 만든다. 구현을 하나 더 두는 것은 생각보다
약한 보호이기도 하다 — 같은 스펙 문장을 읽고 연달아 쓰면 같은 오독을 두 번 할 수
있고, 그것을 막는 것은 **테이블 데이터 자체**(16건)이지 구현의 개수가 아니다.
```

§4.2 의 Emacs 쪽을 구체화한다:

```markdown
세 구현 모두 `testdata/review/*.json`을 검증해야 한다(MUST). Python은
`jsonschema`, TypeScript는 `ajv`, Emacs는 `mrq-schema-test.el` 이 **실제 리더로
읽어** 필수 필드와 `enum` 값을 확인한다 — 별도 검증기를 두지 않고 리더를 통과시키는
이유는, 잡으려는 드리프트가 "CLI 가 쓴 것을 에디터가 못 읽는 것" 이기 때문이다.
```

- [ ] **Step 7: `CLAUDE.md` 에 함정 한 줄**

"반드시 지킬 것" 목록에 더한다:

```markdown
- **`review.json` 에 파일 watch 를 걸지 말 것.** CLI 가 `os.replace` 로 쓰므로
  inode 가 바뀌고 watch 가 첫 쓰기 뒤 조용히 죽는다. 디렉터리에 건다.
  테스트는 **두 번 연속** 고쳐야 이 결함을 본다. `docs/spec/editor.md` §3.1
```

그리고 구조 표의 `plugin_emacs/` 줄을 `elisp  make + batch ERT, 격리된 .elpa` 로
갱신한다.

- [ ] **Step 8: 실측 체크리스트를 쓴다**

`docs/plans/2026-10-14-plugin-emacs-dogfood.md` — 사용자가 자기 Emacs 에서
돌릴 것. 배치 ERT 가 못 잡는 것만 담는다:

```markdown
# 실측 체크리스트 — `plugin_emacs`

배치 ERT 가 못 잡는 것만 모았다: 실제 설정과의 상호작용, 키 바인딩 충돌,
사람이 메시지를 실제로 **알아채는지**.

대상: `gitlab.com/jngbng/mr-helper` MR `!1` (코멘트 15개).

## 준비

```elisp
;; ~/.emacs.d/modules_jbseo/init-mrq.el
(use-package mrq
  :load-path "~/workspace/mrq/plugin_emacs"
  :commands (mrq-setup mrq-mode)
  :hook (prog-mode . mrq-setup))
```

```sh
cd ~/workspace/mr-helper && mrq pull
```

## 체크

- [ ] 소스 파일을 열면 코멘트가 `:note` 진단으로 뜬다
- [ ] **다른 flymake 백엔드와 공존한다** — 파이썬/elisp 버퍼에서 기존 린터 진단과
      섞여 뜨고, 어느 쪽도 사라지지 않는다
- [ ] `M-g n` / `M-g p` 가 코멘트 사이를 돈다
- [ ] **키 바인딩이 충돌하지 않는다** — `C-c m r` 이 기존 바인딩을 덮지 않는다
      (`C-h k C-c m r` 로 확인)
- [ ] `C-c m r` → `review.md` 의 해당 `### reply` 로 간다
- [ ] 답글을 쓰고 저장 → `sync` 가 돌고 **커서가 그 자리에 남는다**
- [ ] 저장 후 열린 소스 버퍼의 진단이 **자동으로** 갱신된다 (watch)
- [ ] 터미널에서 `mrq reply <id> -m "x"` 를 돌리면 Emacs 쪽 진단이 갱신된다
- [ ] `C-c C-t` 로 체크박스를 돌리고 저장 → 상태가 반영된다
- [ ] `g`(pull) / `r`(reanchor) 가 동작하고 버퍼가 갱신된다
- [ ] `C-c C-p` 가 status 요약을 보여주고 확인을 받는다

## 관찰 항목 (잠정 결정의 재평가)

`editor.md` §3.4 는 **위치 없는 경고**를 에코 영역과 `*mrq*` 로만 보내기로 했고,
그 선택을 "잠정" 으로 표시했다 (`mrq-design.md` §6). 지금 그 경고가 알리는 것은
**"답글을 썼는데 전송되지 않는다"** 이고, 놓치면 답글이 그대로 남는다.

- [ ] 답글을 쓰고 체크박스를 `[ ]` 로 **둔 채** 저장한다
- [ ] 그 경고를 **알아챘는가?** 에코 영역은 다른 메시지에 금방 덮인다
- [ ] 알아채지 못했다면: `*mrq*` 를 자동으로 띄울지, 헤더라인에 남길지,
      아니면 `review.md` 안에 경고를 렌더할지 — `mrq-design.md` §6 에 결론을 적는다

## 문제가 있으면

`*mrq*` 버퍼와 `*Messages*` 를 함께 붙여 주면 된다.
`M-x toggle-debug-on-error` 뒤 재현하면 백트레이스가 남는다.
```

- [ ] **Step 9: `plans/README.md` 를 갱신하고 계획서를 지운다**

계획 4 행을 `**완료** (2026-10-14, N 커밋)` 로 바꾸고, 11단계 행도 완료로.
"## 계획 4 — `plugin_emacs` (11단계)" 섹션을 완료 서술로 바꾼다:

```markdown
## 계획 4 — 완료

11단계. flymake 백엔드와 `review.md` 목록 버퍼. 소스 ↔ 코멘트 왕복이 닫힌다 —
`M-g n` 으로 코멘트를 돌고, `C-c m r` 로 답글을 쓰고, 저장하면 `sync` 가 돌고,
`file-notify` 가 열린 버퍼의 진단을 갱신한다.

구현된 FR: FR-014.

**`testdata/conformance/anchor.json` 16건이 이 계획의 가장 오래 남는 산출물이다.**
계획 5 가 그것을 통과해야 하고, 스펙 문장만으로는 안 잡히는 다섯 가지를 못박는다 —
exact 가 둘일 때 strip 으로 내려가지 않는 것, 창 경계의 포함 여부, 공백뿐인 앵커,
버퍼 밖 `location_line`, trailing 공백.

설계에서 스펙에 반영된 것 셋 — `review.json` 이 아니라 **디렉터리**에 watch 를
건다(`os.replace` 가 inode 를 바꾼다, `editor.md` §3.1), 점 이동을 위한 검색은
파싱이 아니다(§1), 충돌 버퍼는 모든 선택을 모아 한 번의 `sync` 로 보낸다(§3.4,
결정 0013).

**실측은 `2026-10-14-plugin-emacs-dogfood.md`.** 배치 ERT 가 못 잡는 것만 담겨
있고, 위치 없는 경고의 가시성(잠정 결정)을 재평가하는 관찰 항목이 들어 있다.
```

계획 5 섹션의 "**계획 4의 적합성 테이블을 통과해야 한다**" 를 그대로 두되
`testdata/conformance/anchor.json` 의 16건과 `buffer_set` 포맷을 언급한다.

```bash
git rm docs/plans/2026-10-14-plugin-emacs-design.md \
       docs/plans/2026-10-14-plugin-emacs.md \
       docs/plans/2026-10-14-pre-step4-prefer-scope.md
```

> **지우기 전에 확인:** CLAUDE.md "작업 방식" — "계획서에만 있던 내용(모듈 분해,
> 제약)은 지우기 전에 스펙으로 옮긴다." Step 1~7 이 그것이다. 지우기 전에
> `grep -n 'plugin_emacs' docs/spec/*.md` 로 모듈 분해가 스펙에 남았는지 본다.

- [ ] **Step 10: 전체 확인과 Commit**

```bash
make test && make lint && make conformance
git add -A docs/ CLAUDE.md
git commit -m "계획 4 완료 — 스펙 반영, 실측 체크리스트, 계획서 정리"
```

---

## 완료 조건

- [ ] `make test` 전부 통과 (cli 525+ · emacs 55+)
- [ ] `make lint` 경고 0 (ruff + byte-compile-error-on-warn + checkdoc)
- [ ] `make conformance` 16건 통과
- [ ] `mrq-boundary-test.el` 넷 통과 — `editor.md` §1 이 코드 모양으로 고정됨
- [ ] `~/.emacs.d` 가 변경되지 않았다 (`.elpa` 격리)
- [ ] `docs/plans/` 에 설계·계획서가 남아 있지 않고, 실측 체크리스트만 있다
