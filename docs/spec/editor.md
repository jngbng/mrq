# 스펙: 에디터 통합

규범 문서. 관련: FR-014, FR-015

---

## 1. 세 구현이 공유하는 계약

Python CLI, `mrq.el`, VSCode 확장이 같은 데이터를 다룬다. 다음 다섯 줄이 에디터
플러그인의 역할 경계다.

1. **`review.json`만 읽는다.** `review.md`를 파싱하지 않는다(MUST NOT)
2. **상태 변경은 `mrq reply` / `mrq state` / `mrq sync`로만 한다.**
   `review.json`을 직접 쓰지 않는다(MUST NOT)
3. **위치 보정은 `docs/spec/reanchoring.md` §6의 범위만** 수행한다.
   보정을 **부르는 쪽**의 규범 넷:
   1. `buffer-modified-p`가 nil이면 **보정을 건너뛴다** — §6의 범위가 "저장하지
      않은 버퍼"다. 저장된 버퍼의 위치는 CLI가 git으로 계산한 값이고 그쪽이
      언제나 더 낫다 (hunk 맵과 context 점수를 쓸 수 있는 쪽은 CLI뿐이다)
   2. 보정이 `d`줄 옮기면 **`location.line_end`에도 같은 `d`를 더한다** —
      멀티라인 코멘트의 span을 잃지 않는다
   3. 진단을 만들 때 **버퍼 범위로 clamp 한다.** 버퍼가 줄면 `location.line`이
      버퍼 밖을 가리키는데 CLI는 디스크 파일만 보므로 그 경우를 모른다
   4. `location`이 `null`이거나 `confidence == "stale"`이면 진단 자체가 없으므로
      보정을 부르지 않는다
4. **`git`과 네트워크를 호출하지 않는다**(MUST NOT)
5. **`review.json`을 파일 감시로 추적해** 진단을 갱신한다(MUST)
6. **`schema_version`을 확인한다.** 모르는 버전이면 명확한 메시지와 함께 동작을
   거부한다(MUST). CLI 버전을 보지 않는다 — 에디터와 CLI를 따로 업데이트해도
   조용히 깨지지 않아야 한다
7. **`testdata/conformance/anchor.json`을 통과해야 한다**(MUST). 3번의 보정 로직이
   세 구현에서 같게 동작하는지를 강제하는 유일한 장치다 (`repo-layout.md` §4.1)

**1번의 경계.** `review.md`에서 **점(point)을 옮기고 화면을 그리기 위한 검색**은
파싱이 아니다. 금지되는 것은 **md에서 읽은 값으로 `review.json`·전송·상태를 바꾸는
것**이다 — 그 값을 읽는 경로는 `review.json` 하나이고, md → json 변환은 `mrq sync`
하나다. 점 이동이 틀리면 커서가 엉뚱한 데 가고 사용자가 즉시 보지만, 값이 쓰기
경로로 들어가면 답글이 조용히 사라진다.

그래서 헤더에서 `path`와 `line`을 읽어 `RET`으로 점프하는 것은 **허용된다**
(§3.2가 요구한다). `local.state`/`local.reply`를 읽어 어딘가에 반영하는 것은
금지된다.

그 경계가 실제로 묶는 것 둘:

- 체크박스 토글(§3.2 `C-c C-t`)은 **버퍼 텍스트만 고치고** 상태를 자기가 해석하지
  않는다. `[ ]→[x]→[~]→[-]` 순환은 문자 치환이고 의미는 `sync`가 준다
- `g`/`r` 뒤의 버퍼 되읽기는 md를 다시 읽는 게 아니라 `revert-buffer`다

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
- **서버에서 resolve 됐고 미전송 작업이 없는 스레드는 표시하지 않는다**
  (`review-md.md` §5와 같은 규칙). 이 규칙이 없으면 동료가 코멘트를 resolve 한 뒤
  `review.md`·`mrq list`에서는 사라진 것이 flymake에만 남아, 사람과 AI가 다른
  집합을 본다(`decisions/0001-human-and-ai-are-peers.md`)
- `mrq-show-handled`는 위의 상태 필터와 이 가시성 필터를 **함께 끈다** —
  `mrq list --all`과 같은 집합이 된다. `location`/`stale` 규칙은 MUST라 끄지 않는다
- `confidence == "fuzzy"`는 메시지에 `[fuzzy]`를 붙인다(SHOULD)
- 메시지는 한 줄: `@jdoe: 타임아웃 설정이 빠졌습니다… [fuzzy]`
- 진단마다 thread id를 text property로 달아 `mrq-reply-at-point`가 쓸 수 있게 한다(MUST)
- 같은 줄에 스레드가 여럿이면 진단도 여럿이다. 합치지 않는다
- `review.json`의 변경을 감시해 열린 버퍼 전체의 flymake를 다시 돌린다(MUST).
  **감시는 파일이 아니라 그 디렉터리에 건다**(SHOULD) — CLI가 temp 파일 +
  `os.replace`로 쓰므로 inode가 바뀌고, 원시 inotify에서는 파일에 건 watch가 첫
  교체 뒤 끊긴 inode에 남아 조용히 죽는다. 덤으로 첫 `pull`이 json을 **만드는**
  순간도 잡는다.

  Emacs에서는 둘이 동등하다 — `file-notify-add-watch`는 FILE을 받아도 부모
  디렉터리를 감시하고 이름으로 거른다(실측). 그래도 디렉터리에 명시적으로 거는
  이유는 동작이 그 구현 세부에 기대지 않게 하려는 것이고, VSCode의
  `FileSystemWatcher`는 같은 보장을 준다고 가정할 수 없기 때문이다 — **계획 5가
  거기서 따로 확인해야 한다.**

  **테스트는 두 번 이상 연속으로 고쳐야 한다**(MUST). 한 번만 보는 테스트는 끊긴
  watch를 통과시킨다

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

정규식은 **상수 하나**로 두고 `next-error`와 `RET`이 함께 쓴다(SHOULD) — 정의가
둘로 갈라지면 `M-g n`과 `RET`이 다른 데로 간다.

경로가 **리포 상대**인 것이 함정이다. `review.md`는 `.mrq/<iid>/`에 있으므로
`default-directory` 기준으로 풀면 틀린다. 리포 루트 기준으로 직접 해석한다(MUST).

| 키 | 동작 |
|---|---|
| `RET` | 해당 소스 위치로 이동 |
| `C-c C-t` | 체크박스 토글 `[ ]` → `[x]` → `[~]` → `[-]` |
| `C-c C-s` | `mrq sync` |
| `C-c C-p` | `mrq push` (`status` 요약을 보여주고 확인) |
| `C-c C-g` | `mrq pull` 후 버퍼 되읽기 |
| `C-c C-r` | `mrq reanchor` |

**평문 키를 명령에 묶지 않는다**(MUST NOT). 이 버퍼는 `markdown-mode` 파생의
**편집면**이고 답글을 여기서 쓴다 — `g`/`r`을 묶으면 "retry 로직을 고쳤습니다"의
첫 글자가 `mrq reanchor`를 돌린다. 목록 버퍼라는 이름 때문에 magit류 읽기 전용
버퍼를 가정하기 쉬운데, 그렇지 않다.

**md 를 다시 쓰는 명령은 미저장 편집 위에서 거부한다**(MUST). `pull`·`reanchor`·
`push`가 그렇다. `sync`는 거부 대신 **저장한다** — `sync`는 디스크의 md를 읽으므로
저장하지 않고 부르면 CLI가 옛 내용을 반영하고 재렌더가 작성 중인 답글을 덮어쓴다.

**버퍼의 리뷰 디렉터리가 `.mrq/current`가 아니면 거부한다**(MUST). `sync`에는
`--mr`이 없으므로(`cli.md` §1), `.mrq/3/review.md`를 열어 둔 채 저장하면 `current`가
가리키는 **다른 MR**이 sync 된다 — MR 3의 답글은 디스크에만 남고 다음 재렌더에
사라진다.

소스 버퍼에서는 `C-c m r`이 `mrq-reply-at-point` — `review.md`를 열어 해당 스레드의
`### reply` 섹션으로 점프한다. 답글은 md에서 작성한다. 소스 ↔ 목록 왕복이 이것으로
닫힌다.

### 3.3 저장 훅

| 저장한 파일 | 동작 |
|---|---|
| `review.md` | `mrq sync` (md 반영 + 재앵커링 + md 재렌더) |
| 소스 파일 | **아무것도 하지 않는다** |

저장 훅은 `sync` 뒤에 버퍼를 되읽어야 하고(`sync`가 md를 다시 쓴다, `cli.md` §5
5단계), **point는 줄 번호가 아니라 스레드 id로 복원한다**(SHOULD) — 재렌더로 앞
블록의 줄 수가 바뀌면 줄 번호 복원은 커서를 흘려보낸다. 답글을 쓸 때마다 일어난다.

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
보여주고 `m`(md 채택) / `j`(json 유지)로 선택한다. `M`/`J`가 전체를 한 방향으로
채우고 개별 키가 그것을 덮는다 — CLI의 스코프 우선 규칙과 같은 모양이다.

**선택은 표시만 하고, 모든 충돌에 방향이 정해진 뒤 한 번의
`mrq sync --prefer <id>=md|json ...` 으로 보낸다**(MUST). 키를 누를 때마다 `sync`를
부르면 안 된다(MUST NOT) — `data-model.md` §5.3이 "충돌이 하나라도 남으면 아무것도
쓰지 않고 exit 3"을 MUST로 두므로 **첫 키부터 실패한다.** 고르지 않은 스레드가
남아 있으면 적용을 거부하고 그리로 point를 옮긴다. 해소가 실패하면 버퍼를 닫지
않는다 — 닫으면 사용자가 선택을 처음부터 다시 해야 한다. 문법과 근거는
[0013](../decisions/0013-scoped-conflict-resolution.md).

이 UI가 없으면 충돌을 보여줄 수는 있어도 **해소할 방법이 없다** — 사용자가 md를
수동으로 되돌리는 수밖에 없고, json 값을 모르면 그것도 불가능하다.

### 3.5 테스트

ERT로 검증한다. `make test-emacs`가 `plugin_emacs/test/*-test.el` 전부를
`emacs -Q -batch`로 돌린다. `markdown-mode`는 `plugin_emacs/.elpa/`에만
설치한다(MUST) — 사용자의 `~/.emacs.d`를 건드리지 않는다.

| 파일 | 덮는 것 |
|---|---|
| `mrq-anchor-test.el` | `testdata/conformance/anchor.json` 16건 |
| `mrq-core-test.el` | 탐색(심링크/일반 파일), 캐시, watch 두 번 연속, `current` 교체, `.mrq` 생기기 전 버퍼, `schema_version` 거부 |
| `mrq-schema-test.el` | `testdata/review/*.json`을 **실제 리더로** 읽기 (`repo-layout.md` §4.2) |
| `mrq-flymake-test.el` | §3.1의 필터, 버퍼 내 보정, clamp, 멀티라인 span, 같은 줄 중복 |
| `mrq-cli-test.el` | stdout/stderr 분리, 종료 코드, stdin, 실행 파일 부재 |
| `mrq-conflict-test.el` | 표시·전체채움·미선택 거부·인자 조립·실패 시 유지 |
| `mrq-mode-test.el` | 헤더 정규식, 체크박스 순환, `RET`, `next-error`, 저장 훅의 point 복원, `mrq-reply-at-point` |
| `mrq-boundary-test.el` | §1의 경계를 코드 모양으로 — json 파싱·쓰기·git·프로세스가 어느 파일에 있는지 |

`make lint`은 `byte-compile-error-on-warn t`로 바이트컴파일하고 `checkdoc`를
돌린다. **둘 다 종료 코드를 바꾼다**(MUST) — elisp에서 가장 싼 방어이고, 오타,
잘못된 인자 수, 쓰이지 않는 변수, 지연 `require`의 미선언 참조를 전부 여기서 잡는다.

`checkdoc-file`은 경고를 찍기만 하고 종료 코드를 바꾸지 않으므로
`plugin_emacs/tools/checkdoc-gate.el`이 그 출력을 가로채 실패시킨다. 대소문자 규칙
둘("first line should be capitalized", "messages should start with a capital
letter")은 거른다 — 독스트링과 메시지가 한국어라 적용될 수 없고, 그것 때문에
나머지 진짜 경고를 못 쓰게 되는 쪽이 나쁘다.

**batch에서 비동기를 기다릴 때 두 가지를 주의한다**(실측):

- inotify 이벤트는 `read-event`로만 배달된다. `sit-for`·`sleep-for`·
  `accept-process-output` 셋은 `emacs -Q -batch`에서 하나도 흘려보내지 않는다
- `flymake-running-backends`를 폴링하면 안 된다. 동기 백엔드는 flymake가
  "running"으로 등록하기 전에 보고해 버려 그 리스트가 비지 않고, 같은 버퍼의
  다른 백엔드(`python-flymake` 등)는 체커가 없는 환경에서 영영 끝나지 않는다

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
