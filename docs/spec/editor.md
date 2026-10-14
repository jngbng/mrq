# 스펙: 에디터 통합

규범 문서. 관련: FR-014, FR-015

---

## 1. 세 구현이 공유하는 계약

Python CLI, `mrq.el`, VSCode 확장이 같은 데이터를 다룬다. 다음 다섯 줄이 에디터
플러그인의 역할 경계다.

1. **`review.json`만 읽는다.** `review.md`를 파싱하지 않는다(MUST NOT)
2. **상태 변경은 `mrq reply` / `mrq state` / `mrq sync`로만 한다.**
   `review.json`을 직접 쓰지 않는다(MUST NOT)
3. **위치 보정은 `docs/spec/reanchoring.md` §6의 범위만** 수행한다
4. **`git`과 네트워크를 호출하지 않는다**(MUST NOT)
5. **`review.json`을 파일 감시로 추적해** 진단을 갱신한다(MUST)
6. **`schema_version`을 확인한다.** 모르는 버전이면 명확한 메시지와 함께 동작을
   거부한다(MUST). CLI 버전을 보지 않는다 — 에디터와 CLI를 따로 업데이트해도
   조용히 깨지지 않아야 한다
7. **`testdata/conformance/anchor.json`을 통과해야 한다**(MUST). 3번의 보정 로직이
   세 구현에서 같게 동작하는지를 강제하는 유일한 장치다 (`repo-layout.md` §4.1)

5번은 사람과 AI가 동시에 작업하기 때문에 필수다. AI가 `mrq reply`로 json을 고치는
동안 사용자는 소스 버퍼를 보고 있다. mtime을 접근 시점에만 확인하면 그 버퍼의 진단은
사용자가 무언가 하기 전까지 낡은 상태로 남는다.

1번과 2번은 md 파서를 Python 한 곳에만 두기 위한 것이다. 세 곳에 두면 셋이 미묘하게
달라지고, 그 차이가 사용자의 답글을 잃는 형태로 나타난다.

---

## 2. 리뷰 디렉터리 찾기

에디터는 `review.json`의 리포지토리 상대 경로를 절대 경로로 바꿔야 하지만 `git`을
호출할 수 없다.

버퍼의 파일에서 위로 올라가며 **`.mrq/current`를 찾는다**(MUST). 디렉터리 탐색이므로
git 호출이 아니고, 한 번에 리포 루트와 리뷰 디렉터리를 모두 얻는다. json에 절대 경로를
기록해 두는 것보다 안전하다 — 리포가 이동해도 동작한다.

`.mrq/current`가 디렉터리(심링크)면 그대로 쓰고, 일반 파일이면 내용을 iid로 읽어
`.mrq/<iid>/`로 들어간다.

---

## 3. Emacs (`mrq.el`) — FR-014

### 3.1 flymake 백엔드

구현 순서상 가장 먼저 만든다. 가치 대비 코드가 가장 적다.

```elisp
(defun mrq-flymake (report-fn &rest _)
  (funcall report-fn
    (mapcar #'mrq--diagnostic (mrq--threads-for buffer-file-name))))

(defun mrq-setup ()
  (add-hook 'flymake-diagnostic-functions #'mrq-flymake nil t)
  (flymake-mode 1))
```

- severity는 `:note`를 쓴다(MUST). 컴파일 에러와 섞이지 않는다
- 기본적으로 `local.state == "todo"`만 표시한다(SHOULD). `mrq-show-handled`로 전체를
  켠다. 120초 예산에서 보고 싶은 것은 "남은 것"이다
- `confidence == "stale"`은 표시하지 않는다(MUST)
- `location == null`인 스레드는 진단을 만들지 않는다(MUST)
- `confidence == "fuzzy"`는 메시지에 `[fuzzy]`를 붙인다(SHOULD)
- 메시지는 한 줄: `@jdoe: 타임아웃 설정이 빠졌습니다… [fuzzy]`
- 진단마다 thread id를 text property로 달아 `mrq-reply-at-point`가 쓸 수 있게 한다(MUST)
- 같은 줄에 스레드가 여럿이면 진단도 여럿이다. 합치지 않는다
- `review.json`에 `file-notify-add-watch`를 걸고 변경 시 열린 버퍼 전체의 flymake를
  다시 돌린다(MUST)

`flymake-goto-next-error` / `flymake-goto-prev-error`가 그대로 "다음/이전 MR
코멘트로 이동"이 된다. 별도 명령을 만들 필요가 없다.

### 3.2 목록 버퍼 (`mrq-mode`)

```elisp
(define-derived-mode mrq-mode markdown-mode "MRQ"
  (setq-local compilation-error-regexp-alist '(mrq))
  (setq-local next-error-function #'mrq-next-error)
  (add-hook 'after-save-hook #'mrq-after-save nil t))
```

정규식은 `^## \[.\] \(.+?\):\([0-9]+\)`이다. `next-error-function`만 채우면
`M-g n` / `M-g p`가 목록 버퍼에서 바로 동작한다.

| 키 | 동작 |
|---|---|
| `RET` | 해당 소스 위치로 이동 |
| `C-c C-t` | 체크박스 토글 `[ ]` → `[x]` → `[~]` → `[-]` |
| `C-c C-s` | `mrq sync` |
| `C-c C-p` | `mrq push` (`status` 요약을 보여주고 확인) |
| `g` | `mrq pull` 후 버퍼 되읽기 |
| `r` | `mrq reanchor` |

소스 버퍼에서는 `C-c m r`이 `mrq-reply-at-point` — `review.md`를 열어 해당 스레드의
`### reply` 섹션으로 점프한다. 답글은 md에서 작성한다. 소스 ↔ 목록 왕복이 이것으로
닫힌다.

### 3.3 저장 훅

| 저장한 파일 | 동작 |
|---|---|
| `review.md` | `mrq sync` (md 반영 + 재앵커링 + md 재렌더) |
| 소스 파일 | **아무것도 하지 않는다** |

소스 저장마다 `reanchor`를 돌리면 매번 json과 md를 다시 쓰게 되는데 그 비용을 낼
이유가 없다. 세션 중의 드리프트는 버퍼 내 보정이 흡수하고, git 기반 정밀 보정은
`sync`가 한다 — `review.md`를 계속 만지는 워크플로이므로 `sync`는 자연히 자주 돌아간다.
어긋난 느낌이 들면 `r`을 누른다.

### 3.4 에러와 충돌 UI

**exit 2 (파싱 에러)**: stderr의 `review.md:142: ...` 형식을 compilation 버퍼에
넣는다. 이미 그 파일을 보고 있으므로 바로 점프해서 고친다.

**위치 없는 경고 (`warnings[].line == null`)**: 위치를 만들어내지 않는다(MUST NOT).
flymake 는 영역이 필요하므로 진단을 만들지 않고, 메시지 면(에코 영역·`*mrq*`)에
보여준다. VSCode 도 Diagnostic 이 아니라 출력 채널로 보낸다. 가짜 위치가 위치 신뢰를
잃는 가장 빠른 길이라는 것이 `cli.md` §5 와 `data-model.md` §4.9 의 같은 근거다.

**이 선택은 잠정이다.** 메시지 면은 조용해서 사용자가 놓칠 수 있다 — 지금 그 경고가
알리는 것은 "답글을 썼는데 전송되지 않는다" 이고, 놓치면 답글이 그대로 남는다.
계획 4·5 의 초안 구현을 실제로 써 본 뒤 재평가한다 (`mrq-design.md` §6).

**exit 3 (충돌)**: `*mrq conflicts*` 버퍼에 스레드별로 md 쪽 값과 json 쪽 값을 나란히
보여주고 `m`(md 채택) / `j`(json 유지)로 선택한다.

**선택은 표시만 하고, 모든 충돌에 방향이 정해진 뒤 한 번의
`mrq sync --prefer <id>=md|json ...` 으로 보낸다**(MUST). 키를 누를 때마다 `sync` 를
부르면 안 된다(MUST NOT) — `data-model.md` §5.3 이 "충돌이 하나라도 남으면 아무것도
쓰지 않고 exit 3" 을 MUST 로 두므로 **첫 키부터 실패한다.** 고르지 않은 스레드가
남아 있으면 적용을 거부하고 그리로 이동한다. 문법과 근거는
[0013](../decisions/0013-scoped-conflict-resolution.md).

이 UI가 없으면 충돌을 보여줄 수는 있어도 **해소할 방법이 없다** — 사용자가 md를
수동으로 되돌리는 수밖에 없고, json 값을 모르면 그것도 불가능하다.

### 3.5 테스트

ERT로 검증한다. 규범 계약이 에디터의 역할을 작게 묶어두었으므로 범위가 좁다.

- `testdata/conformance/anchor.json` 테이블 (§1-7)
- `compilation-error-regexp-alist` 정규식이 헤더를 잡고 `(general)`은 잡지 않는지
- 체크박스 토글 순환
- 모르는 `schema_version`을 거부하는지

CLI 경로는 `mrq-executable`(defcustom, 기본 `"mrq"`)로 찾는다.

---

## 4. VSCode — FR-015

구현 순서상 마지막이다. §1의 계약을 그대로 따른다.

- `languages.createDiagnosticCollection("mrq")` → 문제 패널과 `F8` 이동이 공짜로 생긴다
- `FileSystemWatcher`로 `review.json`을 감시한다(MUST, §1-5)
- CodeLens에 `✓ Resolve` / `💬 Reply`를 노출하고 **`mrq state` / `mrq reply`를
  호출한다**(MUST). md를 파싱하지 않고 json을 직접 쓰지도 않는다
- 커맨드: `mrq: Pull` / `mrq: Sync` / `mrq: Push` / `mrq: Open review file`
- 저장하지 않은 `TextDocument`에 대해서도 §1-3의 보정을 동일하게 적용하고,
  `testdata/conformance/anchor.json`으로 검증한다
- CLI 경로는 `mrq.executablePath` 설정(기본 `"mrq"`)으로 찾는다

Comments API로 본격적인 스레드 UI를 그릴 수도 있지만 1차 구현에서는 과하다.
Diagnostics + CodeLens로 시작한다.

CLI의 `reply` / `state` 명령이 MVP에 포함된 이유가 이 확장이다 — 프로젝트 규칙상
VSCode는 md를 파싱할 수 없으므로, 상태를 바꿀 다른 경로가 반드시 있어야 한다.

---

## 5. AI 에이전트

에이전트는 별도 플러그인 없이 참여한다. 두 경로가 모두 1급이다.

**md 경로** — `.mrq/current/review.md`를 읽고 고친 뒤 `mrq sync`:

```
.mrq/current/review.md 를 읽고, 각 코멘트를 소스에서 확인한 뒤 수정이 필요하면
코드를 고치고, 해당 스레드를 [x] 로 바꾸고 reply 에 무엇을 했는지 써줘.
동의하지 않으면 [~] 로 두고 이유를 reply 에 써줘. 끝나면 mrq sync 를 실행해줘.
```

**CLI 경로** — `mrq list --json`으로 읽고 `mrq reply` / `mrq state`로 쓴다.
md 문법을 다루지 않아도 되고 충돌 가능성이 낮다.

`review.md` 상단의 `<!-- mrq:help -->` 블록이 md 경로의 프롬프트 역할을 한다.
