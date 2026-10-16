# 설계: 계획 4 전 과제 + `plugin_emacs`

브레인스토밍 산출물. 계획 4 가 끝나면 이 문서는 지우고, 규범은 `docs/spec/` 으로,
갈림길은 `docs/decisions/` 로 옮긴다 (CLAUDE.md "작업 방식").

관련 FR: FR-006(충돌 해소), FR-014(Emacs). 스펙: `spec/editor.md`, `spec/cli.md` §5,
`spec/reanchoring.md` §6, `spec/repo-layout.md` §4.

---

## 0. 왜 둘로 나누는가

계획 4 를 설계하다 **스펙 두 곳이 서로 안 맞는 것**을 발견했다.

`editor.md` §3.4 는 충돌 버퍼에서 **스레드마다** `m`(md 채택) / `j`(json 유지) 를
고르라고 한다. 그런데 `cli.md` §5 의 `sync` 는 `--prefer` 가 **호출 하나당 방향
하나**이고, `--thread` 는 그 방향을 적용할 대상만 좁힌다. 거기에
`data-model.md` §5.3 의 MUST — **충돌이 하나라도 남으면 아무것도 쓰지 않고 exit 3.**

그래서 스레드 A 는 md, B 는 json 으로 고르면 어떤 순서로도 빠져나갈 수 없다:

```
mrq sync --prefer md   --thread A   →  B 가 여전히 충돌  →  exit 3, 아무것도 안 씀
mrq sync --prefer json --thread B   →  A 가 여전히 충돌  →  exit 3, 아무것도 안 씀
```

우회로 둘을 검토했고 둘 다 죽는다:

- `mrq state`/`reply` 로 json 쪽을 먼저 확정한다 → 그 명령들이 `review.md` 를
  **재렌더**하므로(`cli.md` §10 MUST) A 의 md 편집이 지워진다
- 에디터가 md 블록을 json 값으로 직접 고쳐 쓴다 → 렌더러를 elisp 에 복제하는 일이고
  `editor.md` §1-1 의 근거("md 파서를 Python 한 곳에만")를 정면으로 깬다

**CLI 를 먼저 고쳐야 계획 4 의 충돌 UI 가 설계대로 산다.** 계획 3 때
`jbseo/pre_step3` 로 R3·R4 를 분리했던 것과 같은 모양이다.

---

# 1부 — 계획 4 전 과제: `sync --prefer` 스코프 문법

## 1.1 표면

```
이전:  mrq sync [--json] [--prefer md|json] [--thread ID]...
이후:  mrq sync [--json] [--prefer [ID=]md|json]...
```

플래그 수는 그대로인데 **상호작용이 사라진다.** 지금 `--thread` 는 `--prefer` 없이
주면 아무 의미가 없는, 혼자 서지 못하는 플래그다. 스코프 접두사는 혼자 선다.

`--thread` 는 `sync` 에서 **삭제**한다. 소비자가 `mdsync.py:80` 의 `only_refs` 하나뿐이고
production 호출자가 없다. `mrq open --thread` 는 다른 명령이라 그대로 둔다.

### 왜 플래그 둘(`--prefer` + `--pick`)이 아닌가

`--pick ID=dir` 을 따로 두는 안을 먼저 검토했다. `--pick` 은 `--prefer`+`--thread`
조합을 **완전히 흡수하지만** `--prefer` 단독은 흡수하지 못한다 — `--prefer md` 의
값은 "일괄" 이 아니라 **"id 를 타이핑하지 않아도 된다"** 이기 때문이다. 충돌 하나짜리
경우에도 `mrq sync --prefer md` 가 `mrq sync --pick a1b2c3d4=md` 보다 낫고, 이것이
터미널의 사람과 AI 에이전트가 쓰는 경로다(`decisions/0008` 이 두 번 언급한다).

그래서 둘을 합쳐 **선택적 스코프 접두사** 하나로 만든다. 널리 쓰이는 관용구다 —
`RUST_LOG=debug` 대 `RUST_LOG=mycrate=trace`, python `-W error` 대
`-W error::DeprecationWarning:mymod`.

### 왜 `all=` 을 요구하지 않는가

`--prefer [all|ID]=md|json` 으로 문법을 완전히 균일하게 만드는 안도 검토했다.
유일한 이득은 synopsis 의 깔끔함인데, `[ID=]` 표기가 같은 깔끔함을 주면서
**공통 경우를 길게 만들지 않는다.** 충돌 자체가 드물고 혼합 방향은 더 드물다 —
95% 의 경우에 `all=` 을 치게 해서 5% 를 균일하게 만드는 것은 방향이 반대다.
덤으로 `--prefer md` 는 `cli.md`·`data-model.md`·`testing.md`·`decisions/0008`
(두 번)에 이미 박혀 있어 churn 이 0 이다.

## 1.2 해소 규칙 — 좁은 스코프가 순서와 무관하게 이긴다

> **스코프가 좁은 쪽이 순서와 무관하게 이긴다. 같은 스코프 안에서는 뒤가 이긴다.**

```sh
mrq sync --prefer md                          # 전부 md
mrq sync --prefer md --prefer f6e5=json       # 전부 md, f6e5 만 json
mrq sync --prefer f6e5=json --prefer md       # ← 위와 같은 결과 (순서 무관)
mrq sync --prefer md --prefer json            # 같은 스코프 반복 → json
mrq sync --prefer a1b2=md --prefer a1b2=json  # 같은 스코프 반복 → json
```

위치 기반 fold(뒤가 앞을 무조건 덮음)도 검토했고 버렸다. fold 는 "앞의 개별 지정을
뒤의 전역 항목이 지운다"는 모서리를 만드는데, 많은 도구가 반대로 동작하므로
(`chmod`, `.gitignore`, CSS, `RUST_LOG`) 반대로 기대하는 사람이 생긴다. 스코프
우선은 그 모서리가 아예 없고, 구현도 더 짧다 — fold 는 전역 항목을 만날 때마다
쌓인 개별 지정을 비워야 한다.

```python
default = None   # 스코프 없는 항목, 뒤가 덮는다
picks = {}       # thread_id → 방향, 뒤가 덮는다
# 해소: picks.get(thread_id, default)
```

잃는 것 하나: 앞의 `ID=` 지정을 뒤에 `--prefer md` 를 붙여 **취소할 수 없다.**
취소하려면 그 `ID=` 를 반대 방향으로 다시 줘야 한다. 명시적으로 고른 것이 나중
항목에 조용히 지워지지 않는 쪽이 맞다.

## 1.3 파싱과 가드

- `=` 를 포함하면 `ID=방향`, 아니면 방향 단독. 방향은 `md` 또는 `json`
- `ID` 는 **유일한 접두사**를 받는다(`threads.resolve_ref`, `cli.md` §1).
  여러 스레드에 걸리면 exit 1 + 후보 목록
- **스코프 없는 값이 실제 스레드 접두사와 겹치면 exit 1.** discussion id 는 SHA1
  16진수이고(`[0-9a-f]`) `md` 의 `m`, `json` 의 `j`·`s`·`o`·`n` 은 16진수가 아니므로
  도달 불가다. 그래도 가드를 둬서 **가정을 불변식으로 바꾼다** — 이 사실이 깨지면
  조용한 오동작이 아니라 에러가 난다
- `ID=` 가 **충돌이 아닌 스레드**를 지목하면 stderr 로 경고하고 동작은 그대로 둔다
  (`a1b2c3: 충돌이 아닙니다, 무시합니다`). 오타가 조용히 삼켜지는 것을 막는다
- `--prefer` 는 **충돌로 판정된 스레드에만** 적용된다 (`conflict.py:98` 의 현재
  동작 유지)

## 1.4 손볼 곳

| 파일 | 내용 |
|---|---|
| `cli/src/mrq/cli.py` | `--prefer` 를 `append` 로, `--thread` 삭제 |
| `cli/src/mrq/mdsync.py` | `prefer`/`only_refs` → `default`/`picks`, 경고, 메시지(§182) |
| `cli/src/mrq/conflict.py` | `plan_sync` 의 해소 분기 |
| `cli/src/mrq/threads.py` | 독스트링(§6) |
| `docs/spec/cli.md` | §1 synopsis, §5 해소 설명 + 예시 |
| `docs/spec/data-model.md` | §5.3 |
| `docs/spec/editor.md` | §3.4 (2부에서 함께) |
| `docs/spec/testing.md` | §179 |
| `docs/decisions/0002-...md` | 한 줄 |
| `docs/decisions/0013-...md` | **새 기록** — 아래 |

`decisions/0013-scoped-conflict-resolution.md` 를 추가한다. 0002 가 고른 갈림길
(스레드 단위 충돌 **판정**)은 그대로이고, 새로 고른 것은 **해소도 스레드 단위로
섞을 수 있어야 한다**이다. 그 선택이 스펙 둘의 모순에서 강제됐다는 것과, 버린
대안 셋(`--pick` 별도 플래그 / `all=` 균일 문법 / 위치 fold)을 적는다.

## 1.5 테스트

| # | 케이스 | 기대 |
|---|---|---|
| 1 | `--prefer md` | 충돌 전부 md |
| 2 | `--prefer a1b2=md` 만, 다른 충돌 존재 | **exit 3, 아무것도 안 씀** |
| 3 | `--prefer md --prefer f6e5=json` | 혼합 |
| 4 | 3번의 인자 순서를 뒤집음 | 3번과 동일 |
| 5 | 같은 스코프 반복 (전역·개별 각각) | 뒤가 이긴다 |
| 6 | `ID=` 가 충돌 아닌 스레드를 지목 | stderr 경고, 동작 불변 |
| 7 | `ID` 접두사가 여럿에 걸림 | exit 1 + 후보 |
| 8 | 스코프 없는 값이 실제 스레드 접두사와 겹침 | exit 1 (불변식 가드) |
| 9 | `--prefer` 없이 충돌 | exit 3, 안내 메시지에 새 문법 |

2번이 가장 중요하다 — **부분 해소는 여전히 전부 실패**이고, 그것이 2부의 충돌 UI
모양을 결정한다.

---

# 2부 — 계획 4: `plugin_emacs`

## 2.1 범위와 경계

`editor.md` §1 의 일곱 줄이 역할 경계다. 요약하면: `review.json` 만 읽고,
`review.md` 를 파싱하지 않고, json 을 직접 쓰지 않고, git·네트워크를 부르지 않고,
`schema_version` 을 보고, 파일 감시로 진단을 갱신하고, 적합성 테이블을 통과한다.

### §1-1 에 추가할 경계 문장

`§1-1`(md 파싱 금지)과 `§3.2`(`C-c m r` 이 `review.md` 의 `### reply` 로 점프)가
서로 당긴다. 점프하려면 그 버퍼에서 `<!-- mrq:<id> ` 를 찾아야 한다.

> `review.md` 에서 **점(point)을 옮기기 위한 검색**은 파싱이 아니다. 금지되는 것은
> md 에서 `local.state` / `local.reply` 를 **추출하는 것**이다 — 그 값을 읽는 경로는
> `review.json` 하나이고, md → json 변환은 `mrq sync` 하나다.

§1-1 의 근거가 "md 파서를 Python 한 곳에만 두어 셋이 어긋나 답글을 잃는 것을 막는다"
이므로, 점 이동은 그 손해를 만들지 않는다 — 틀려야 커서가 엉뚱한 데 가고 사용자가
즉시 본다. 같은 근거로 `compilation-error-regexp-alist` 도 허용된다(§3.2 가 명시적으로
요구하고 §3.5 가 그 정규식을 테스트하라고 한다).

그 제약이 실제로 묶는 것 둘도 함께 적는다:

- `C-c C-t` 체크박스 토글은 **버퍼 텍스트만 고치고** 상태를 자기가 해석하지 않는다.
  `[ ]→[x]→[~]→[-]` 순환은 문자 치환이고, 의미는 `sync` 가 준다
- `g`/`r` 뒤의 버퍼 되읽기는 md 를 다시 읽는 게 아니라 `revert-buffer` 다

## 2.2 파일 분할

```
plugin_emacs/
  mrq.el              진입점. autoload 쿠키, mrq-setup, 패키지 헤더
  mrq-core.el         리뷰 상태 접근 계층 — 단 하나의 읽기 창구
  mrq-anchor.el       §6 앵커 보정. 순수 함수. 적합성 테이블의 대상
  mrq-cli.el          mrq 프로세스 호출 계층
  mrq-flymake.el      flymake 백엔드
  mrq-mode.el         review.md 목록 버퍼, 저장 훅, 키맵, next-error
  mrq-conflict.el     *mrq conflicts* 버퍼 (exit 3 UI)
  Makefile
  test/
    mrq-test-helper.el
    mrq-<모듈>-test.el
```

의존은 한쪽으로만 흐른다 (순환 없음):

```
mrq.el          ──▶ 전부 (autoload 로만)
mrq-flymake.el  ──▶ mrq-core, mrq-anchor
mrq-mode.el     ──▶ mrq-core, mrq-cli, mrq-conflict
mrq-conflict.el ──▶ mrq-core, mrq-cli
mrq-cli.el      ──▶ mrq-core (defgroup 때문에만)
mrq-core.el     ──▶ Emacs 내장만
mrq-anchor.el   ──▶ Emacs 내장만
```

| 모듈 | 책임 |
|---|---|
| `mrq-anchor.el` | `(lines anchor-line location-line) → line`. 의존 0, 부작용 0. 버퍼도 파일도 모른다 |
| `mrq-core.el` | `.mrq/current` 상향 탐색, `review.json` 읽기·`schema_version` 검사·캐시·`file-notify`. **json 을 읽는 코드는 여기 말고 없다** |
| `mrq-cli.el` | `mrq` 실행, 종료 코드 + stdout/stderr 분리 반환. **프로세스를 띄우는 코드는 여기 말고 없다** |
| `mrq-flymake.el` | 스레드 → 진단 변환, §3.1 의 필터 |
| `mrq-mode.el` | `review.md` 메이저 모드. 키맵, `next-error`, `after-save-hook` |
| `mrq-conflict.el` | 충돌 페이로드 → 버퍼, 선택 수집, `sync` 인자 조립 |

`defgroup mrq` 와 사용자 변수는 **`mrq-core.el`** 에 둔다 — `mrq-executable`
(`repo-layout.md` §5), `mrq-show-handled`(§3.1). `mrq.el` 에 두면 다른 모듈이
`mrq.el` 을 require 해야 해서 순환이 생긴다.

`mrq.el` 은 autoload 쿠키(`mrq-setup`, `mrq-mode`, `auto-mode-alist`)와 패키지
헤더만 담는다. `mrq-setup` 이 호출될 때 `mrq-flymake` 를 require 한다 — 로드 시점에
전부 끌어오지 않는다.

이 분할이 사는 자리 셋:

1. **`mrq-anchor.el` 이 의존 0 이라** 적합성 테이블 테스트가 Emacs 내장만으로 돈다.
   계획 5 의 `anchor.ts` 와 1:1 로 대응된다
2. **`markdown-mode` 의존이 `mrq-mode.el` 하나에 갇힌다.** 일곱 중 여섯의 테스트가
   `emacs -Q -batch` 에서 바로 돈다
3. **`mrq-core.el` 이 유일한 읽기 창구라** §1-1·§1-2 가 코드 모양으로 확인된다 —
   `mrq-core.el` 에 쓰기 함수가 없고 다른 파일에 `json-parse` 가 없으면 끝이다.
   메타 테스트로 고정한다

패키지 헤더는 `Package-Requires: ((emacs "29.1") (markdown-mode "2.5"))`.
Eask 도 `mrq-pkg.el` 도 만들지 않는다 — `:load-path` 로 쓰는 동안은 헤더로 충분하고
MELPA 는 future work 다(`plans/README.md` 계획 4).

## 2.3 앵커 보정 (`mrq-anchor.el`)

```elisp
(mrq-anchor-correct LINES ANCHOR-LINE LOCATION-LINE) → 줄 번호
```

`LINES` 는 1-indexed 문자열 벡터.

```
WINDOW = 200
lo = max(1, location-line - 200)
hi = min(length(lines), location-line + 200)
창이 비면 → location-line

exact = [i in lo..hi : lines[i] == anchor-line]

anchor-line 이 공백뿐이면:
    exact 가 정확히 1건 → 그 줄.  아니면 → location-line   (strip 단계 없음)

exact 가 정확히 1건 → 그 줄
exact 가 2건 이상  → location-line          (strip 으로 내려가지 않는다)

stripped = [i in lo..hi : trim(lines[i]) == trim(anchor-line)]
stripped 가 정확히 1건 → 그 줄.  아니면 → location-line
```

`trim` 은 **양쪽 끝의 공백과 탭 제거**다. 세 언어의 기본 동작이 여기서 일치한다
(`str.strip()`, `string-trim`, `String.prototype.trim`). 줄 끝 개행은 애초에 줄
배열에 들어오지 않는다.

전체 파일 fallback 도 context 점수도 **없다** — 그 둘은 CLI `search.find` 전용이고
(`reanchoring.md` §6 MUST NOT), CLI 와 다른 알고리즘인 것이 의도다. CLI 는 창 50 +
context 점수 + 전체 파일 fallback 을 쓴다.

### 스펙이 안 정한 것들과 선택

| 애매한 것 | 선택 | 근거 |
|---|---|---|
| exact 후보가 둘 이상이면 strip 으로 내려가나 | **아니오.** exact 가 1건 이상이면 거기서 끝 | 애매한데 더 느슨한 비교로 내려가면 후보가 늘기만 한다 |
| 창 경계가 포함인가 | `[line-200, line+200]` **양끝 포함**, 버퍼 범위로 clamp | — |
| `anchor.line` 이 공백뿐일 때 | **CLI 와 같게** — exact 유일하면 채택, strip 단계는 건너뜀 | `search.py` 가 같은 결정을 하고 이유를 적어 뒀다 |
| `location.line` 이 버퍼보다 클 때 | 창을 clamp 해서 계속 탐색. 못 찾으면 그대로 반환 | 호출부가 clamp 한다 |
| 멀티라인(`line_end`) | 테이블은 **한 줄 검색만** 정의. delta 적용은 호출부 규범 | §6 이 "앵커 한 줄 검색" |
| 인덱싱 | 전부 1-indexed | — |
| 저장된 버퍼 | **보정하지 않는다** | §6 의 범위가 "저장하지 않은 버퍼" |

### 호출부 규범 — `editor.md` 에 추가할 네 줄

1. **`buffer-modified-p` 가 nil 이면 보정을 건너뛴다.** §6 의 범위가
   "저장하지 않은 버퍼" 다
2. 보정이 `d` 줄 옮기면 **`location.line_end` 에도 같은 `d` 를 더한다**.
   R6 이 되살린 span 을 잃지 않는다
3. 진단을 만들 때 **버퍼 범위로 clamp** 한다
4. `location` 이 `null` 이거나 `confidence == "stale"` 이면 진단 자체가 없으므로
   **보정을 부르지 않는다**

## 2.4 적합성 테이블 (`testdata/conformance/anchor.json`)

### 포맷 — `repo-layout.md` §4.1 변경 하나

스펙의 `buffer_insert: {at, line}` 은 **삽입인지 치환인지 애매**하다. 삽입이면 뒤
줄이 전부 밀려 기대값 계산이 어긋나기 쉽고, 후보를 둘 심는 케이스에서 순서 의존이
생긴다.

`buffer_set: [{at, line}, ...]` 으로 바꾼다 — **`at` 번째 줄을 치환**하고 길이는
`count` 그대로이며 순서에 무관하다. 파일은 순수 JSON 이므로(주석 불가) 각 케이스의
`name` 이 문서 역할을 하고, 필드 의미표는 `repo-layout.md` §4.1 에 둔다. 거기에
**전부 1-indexed** 라고 명시한다.

| 필드 | 의미 |
|---|---|
| `name` | 케이스 설명. 실패 메시지에 그대로 나온다 |
| `buffer` | 버퍼 내용. 1-indexed 줄 배열 |
| `buffer_repeat` | `{line, count}` — 큰 버퍼를 json 에 펼치지 않고 생성. `buffer` 와 배타적 |
| `buffer_set` | `[{at, line}]` — `at` 번째 줄을 치환. `buffer_repeat` 와만 함께 쓴다 |
| `anchor_line` | `anchor.line` 값 |
| `location_line` | `location.line` 값 (검색 시작점) |
| `expect` | 기대 줄 번호. 보정하지 않으면 `location_line` 과 같다 |

### 케이스 16건

스펙의 4건(1~4)에 12건을 더한다.

| # | 이름 | 고정하는 것 |
|---|---|---|
| 1 | 유일한 후보를 채택한다 | 기본 동작 |
| 2 | 후보가 둘이면 보정하지 않는다 | 유일성 가드 |
| 3 | 완전 일치가 없으면 strip 일치를 쓴다 | 2단계 |
| 4 | 창 밖은 보지 않는다 | 창의 존재 |
| 5 | exact 가 둘이면 strip 으로 내려가지 않는다 | 버퍼에 exact 2건 + strip-only 1건 → 보정 없음 |
| 6 | 창 경계 `+200` 은 포함 | 후보 201행, `location_line` 1 → 201 |
| 7 | 창 경계 `+201` 은 제외 | 후보 202행 → 1 |
| 8 | 창 경계 `-200` 은 포함 | `location_line` 401, 후보 201행 → 201 |
| 9 | strip 후보가 둘이면 보정하지 않는다 | 2단계에도 같은 가드 |
| 10 | 공백뿐인 앵커: exact 유일하면 채택 | CLI `search.py` 와 같은 규칙 |
| 11 | 공백뿐인 앵커: strip 단계로 안 내려간다 | 앵커 `"  "`, 버퍼에 `"    "` 하나 → 보정 없음 |
| 12 | `location_line` 이 버퍼보다 커도 창을 clamp 해 탐색 | 버퍼 3줄, `location_line` 5, 후보 2행 → 2 |
| 13 | 창이 버퍼와 안 겹치면 보정하지 않는다 | 버퍼 3줄, `location_line` 500 → 500 |
| 14 | 앵커가 아예 없으면 보정하지 않는다 | 실패 경로 |
| 15 | 빈 버퍼 | `lines` 비었음 → `location_line` |
| 16 | trailing 공백은 strip 이 흡수한다 | 앵커 `"x = 1"`, 버퍼 `"x = 1   "` → 그 줄 |

### 파이썬은 이 테이블을 돌리지 않는다

`repo-layout.md` §4.1 은 "세 구현이 **모두** 읽어 같은 테이블을 돌린다(MUST)" 라고
쓰는데, CLI 에는 저장 안 된 버퍼가 없다. 테이블을 돌리려면 **production 호출자가
없는 §6 함수**를 CLI 에 새로 넣어야 하고, 그것은 `search.find` 옆에 앉아 실제로
혼동을 만든다(잔여 항목이 이미 비슷한 드리프트를 지적하고 있다).

§4.1 의 MUST 를 **"앵커 보정을 구현하는 모든 구현"** 으로 좁히고 근거를 적는다.
"기준이 둘" 은 생각보다 약한 보호다 — 같은 에이전트가 같은 스펙 문장을 읽고 연달아
쓰므로 같은 오독을 두 번 할 수 있고, 그것을 막는 것은 **테이블 데이터 자체**(16건)이지
구현의 개수가 아니다.

## 2.5 `mrq-core.el` — 리뷰 상태 접근 계층

```elisp
(mrq-core-review-dir)        ; 버퍼 → 리뷰 디렉터리 (없으면 nil)
(mrq-core-threads-for FILE)  ; 파일 → 그 파일의 스레드 리스트
(mrq-core-review DIR)        ; 파싱된 review.json 전체 (캐시)
(mrq-core-refresh DIR)       ; 캐시 무효화 + 열린 버퍼 flymake 재실행
```

### 함정: `review.json` 에 watch 를 걸면 안 된다

CLI 가 temp 파일에 쓰고 **`os.replace`** 로 교체한다(`store.py:179`). inode 가 바뀌므로
파일에 건 inotify watch 는 **첫 쓰기 이후 조용히 죽는다** — 알림이 안 오는 게 아니라
처음 한 번은 오고 그 뒤로 영영 안 온다. 한 번만 고쳐 보는 테스트는 통과한다.

**리뷰 디렉터리(`.mrq/<iid>/`)에 watch 를 건다.** 이벤트에서 `review.json` 만 거른다.
덤으로 첫 `pull` 이 json 을 **만드는** 순간도 잡힌다. 테스트는 **두 번 이상 연속으로**
고쳐 두 번 다 알림이 오는지 본다.

### 탐색

`locate-dominating-file` 로 `.mrq/current` 를 찾는다. 디렉터리(심링크)면 그대로,
일반 파일이면 내용을 iid 로 읽어 `.mrq/<iid>/`(`data-model.md` §1).

- **리포 루트만 버퍼 로컬에 캐시**하고 `current` 는 접근할 때마다 다시 푼다.
  `pull --mr` 로 다른 MR 을 받으면 심링크가 바뀌는데, 디렉터리를 캐시하면 못 따라간다
- **실패(= `.mrq` 없음)는 캐시하지 않는다.** 첫 `pull` 전에 연 버퍼가 영원히 죽는다

### 캐시와 watch 수명

- 캐시 키는 리뷰 디렉터리. 무효화는 watch 알림으로만. **mtime 비교를 하지 않는다** —
  §1-5 의 근거가 그것이고, 초 단위 mtime 은 같은 초 안의 두 번째 쓰기를 놓친다
- watch 는 리뷰 디렉터리당 하나, 처음 성공적으로 resolve 할 때 등록하고 세션 동안
  유지한다. 해제하지 않는다 — 상한이 "이 세션에서 건드린 MR 수" 라 누수가 아니고,
  버퍼 단위로 걸고 풀면 `kill-buffer` 경로가 전부 샌다

### `schema_version` 거부

모르는 버전이면 진단을 **0개 반환**하고, `(디렉터리, 버전)` 쌍마다 **한 번만**
에코 영역 + `*mrq*` 에 메시지를 낸다. flymake 는 편집 중 반복 호출되므로 매번
`user-error` 를 내면 미니버퍼가 못 쓰게 된다.

**쓰기 함수가 없다.** 그것이 §1-2 를 코드 모양으로 보장한다.

## 2.6 `mrq-flymake.el`

| 조건 | 동작 |
|---|---|
| `location == null` | 진단 없음 (MUST) |
| `confidence == "stale"` | 진단 없음 (MUST) |
| `location.path` ≠ 이 버퍼의 리포 상대 경로 | 진단 없음 |
| `local.state != "todo"` 이고 `mrq-show-handled` 가 nil | 진단 없음 (SHOULD) |
| 위 전부 통과 | `:note` 진단 하나 |

- 줄은 §2.3 보정을 거친 값(`buffer-modified-p` 일 때만), 그 뒤 버퍼 범위로 clamp
- 영역은 `line`~`line_end`(보정 delta 적용), `line_end` 가 null 이면 그 줄 하나
- 메시지 한 줄: `@jdoe: 타임아웃 설정이 빠졌습니다…`, `fuzzy` 면 ` [fuzzy]` 를 붙인다.
  본문은 **루트 노트의 첫 줄**을 자른다
- thread id 를 `flymake-make-diagnostic` 의 `data` 와 overlay property 양쪽에 단다.
  `mrq-reply-at-point` 가 `(flymake-diagnostics (point))` 로 집어 읽는다
- 같은 줄에 스레드가 여럿이면 **진단도 여럿** — 합치지 않는다

`mrq-setup` 은 `flymake-diagnostic-functions` 에 백엔드를 추가하고 `flymake-mode` 를
켠다. **어디에 걸지는 사용자 몫**으로 둔다(`prog-mode-hook` 자동 등록 안 함).
`mrq-core-review-dir` 이 nil 이면 조용히 빠지므로 자동 등록해도 안전하지만, 그
선택은 사용자 config 에서 하는 쪽이 맞다.

## 2.7 `mrq-mode.el` — 목록 버퍼와 저장 훅

### 등록과 정규식

`auto-mode-alist` 에 `"/\\.mrq/[^/]+/review\\.md\\'"` → `mrq-mode` 를 autoload 로
등록한다. 리포 안의 다른 `review.md` 를 가로채지 않는다.

```elisp
(defconst mrq-mode-header-re "^## \\[.\\] \\(.+?\\):\\([0-9]+\\)")
```

`compilation-error-regexp-alist-alist` 에 `mrq` 항목으로도 등록하고, `mrq-next-error`
와 `RET` 둘 다 이 상수를 쓴다 — 정의가 둘로 갈라지면 `M-g n` 과 `RET` 이 다른 데로
간다. ERT 가 이 상수를 직접 때린다: 위치 헤더는 잡고 `(general)` 헤더는 **안 잡아야**
한다(`review-md.md` §3).

경로가 **리포 상대**인 것이 함정이다 — `review.md` 는 `.mrq/<iid>/` 에 있으므로
`default-directory` 기준으로 풀면 틀린다. `mrq-next-error` 와 `RET` 이 **리포 루트
기준으로 직접 해석**한다.

### 키맵

| 키 | 동작 | 비고 |
|---|---|---|
| `RET` | 소스 위치로 이동 | 그 버퍼가 modified 면 §2.3 보정을 적용해서 간다 — 진단과 같은 줄에 선다 |
| `C-c C-t` | `[ ]→[x]→[~]→[-]→[ ]` | point 에서 위로 헤더를 찾아 **문자만 치환** |
| `C-c C-s` | `mrq sync` | |
| `C-c C-p` | `mrq push` | `mrq status` 요약을 보여주고 `y-or-n-p` |
| `g` | `mrq pull` 후 되읽기 | |
| `r` | `mrq reanchor` | |

소스 버퍼의 `C-c m r` = `mrq-reply-at-point`: `(flymake-diagnostics (point))` 에서
thread id 를 집어 → `review.md` 를 다른 창에 열고 → `<!-- mrq:<id> ` 를 검색해 →
그 스레드의 `### reply` 아래 첫 빈 줄에 point 를 둔다. 진단이 없으면 `user-error`.
**이것으로 왕복이 닫힌다**: 소스 → `C-c m r` → 답글 → 저장 → `sync` → watch → 진단 갱신.

### 저장 훅

| 저장한 파일 | 동작 |
|---|---|
| `review.md` | `mrq sync` (동기) |
| 소스 파일 | **아무것도 하지 않는다** |

`sync` 는 `review.md` 를 **다시 쓴다**(`cli.md` §5 5단계). 저장 훅은 sync 뒤에 버퍼를
되읽어야 하고, 그냥 되읽으면 point 가 날아간다.

**point 는 줄 번호가 아니라 스레드 id 로 복원한다.** 저장 전에 point 위의 가장 가까운
앵커 id 와 그 블록 안에서의 오프셋을 기억하고, 되읽은 뒤 같은 id 를 찾아 되돌아간다.
재렌더로 앞쪽 블록의 줄 수가 바뀌어도(배지가 붙거나 `v:` 가 바뀌어도) 커서가 제자리에
선다. 줄 번호로 복원하면 답글을 쓸 때마다 커서가 흘러간다.

동기 실행을 고르는 이유: 실측에서 `sync` 가 0.22초이고, 비동기로 만들면 "sync 가 도는
중에 다시 저장" 과 "되읽기가 사용자의 다음 편집을 덮어씀" 두 경로가 생긴다.

### 종료 코드 분기

저장 훅과 `C-c C-s` 가 같은 함수를 쓴다.

- **0** — 에코 영역에 `applied 14 · exact 12 fuzzy 2 stale 1`. 경고는 §2.8
- **2** — 파싱 에러. 되읽지 **않는다**(CLI 가 아무것도 안 썼고 고칠 내용이 버퍼에 있다)
- **3** — 충돌. 역시 되읽지 않고 §2.9 로

## 2.8 `mrq-cli.el` 과 `*mrq*`

```elisp
(mrq-cli-run ARGS &optional STDIN) → (:code N :json PARSED :stderr STRING)
```

- **stdout 과 stderr 를 반드시 분리한다.** `cli.md` §2 가 "stdout 은 순수 JSON,
  경고는 stderr" 를 MUST 로 두는데 섞으면 파싱이 깨진다. `call-process` 의
  `(list 버퍼 stderr-파일)` 형태를 쓴다
- 본문은 `STDIN` 으로 넘긴다(`call-process-region`). "답글 본문을 인자로 넘기지 말 것"
  을 에디터도 지킨다. 지금 쓰는 경로는 없지만 `mrq reply -F -` 가 생길 자리다
- 동기 실행. 비동기가 필요한 유일한 후보는 `push`(실측 16초)인데 `C-c C-p` 는 확인을
  받고 돌리는 명시적 조작이라 블로킹이 맞다

### `--json` 을 지원하는 명령에는 **항상** `--json` 을 붙인다

`sync` · `status` · `push` · `reanchor` · `list` 가 그렇다(`cli.md` §1). 에디터는
사람용 출력을 파싱하지 않는다 — `sync` 의 exit 3 충돌 UI 가 구조화된 페이로드를
요구하므로(§2.9), 같은 호출이 exit 0 일 때만 평문을 읽는 분기를 만들 이유가 없다.

`pull` · `open` · `clean` · `doctor` · `reply` · `state` 는 `--json` 이 없다. 이들은
**종료 코드만 보고** stderr 를 그대로 `*mrq*` 에 넣는다.

### `*mrq*` 는 하나이고 `compilation-mode` 다

버퍼를 둘로 나누지 않는다. `default-directory` 를 리뷰 디렉터리로 두면
**`review.md:142:` 가 그대로 클릭·`C-x \`` 로 점프**한다.

| 입력 | `*mrq*` | 에코 영역 |
|---|---|---|
| exit 0, 경고 없음 | — | `applied 14 · exact 12 fuzzy 2 stale 1` |
| exit 0, `warnings[].line` 있음 | `review.md:142: …` (점프 가능) | 위 + `경고 2건 (*mrq*)` |
| exit 0, `warnings[].line == null` | 접두사 없는 평문 줄 | 위와 같음 |
| exit 2 | `errors[]` 전부, 점프 가능 | `파싱 에러 2건 — C-x \`` |
| exit 1·5·6·7 | stderr 전문 | stderr 첫 줄 + `user-error` |

**위치 없는 경고에 위치를 만들지 않는다**(§3.4 MUST NOT). `review.md:0` 도 1행도
쓰지 않는다. 이 선택이 잠정이라는 것(`mrq-design.md` §6)을 지켜야 하므로
**실측 체크리스트에 관찰 항목으로 명시**한다 — "답글을 쓰고 `[ ]` 로 둔 채 sync
했을 때 그 경고를 알아챘는가".

## 2.9 충돌 버퍼 (`mrq-conflict.el`)

1부의 결론이 이 UI 를 결정한다: **부분 해소는 여전히 전부 실패**이므로
(`data-model.md` §5.3), 키를 누를 때마다 `sync` 를 부르면 **첫 키부터 실패한다.**

`*mrq conflicts*`, `special-mode` 파생. `sync --json` 의 exit 3 페이로드를 받는다.

```
a1b2c3d4  src/api/client.py:102              → md
  md    [x] 확인했습니다. timeout=10 추가.
  json  [~] AI: 상위에서 설정 중입니다.

f6e5d4c3  src/api/legacy.py:1                → ?
  md    [-] 의도된 동작입니다.
  json  [ ]
```

| 키 | 동작 |
|---|---|
| `m` / `j` | 그 스레드에 선택을 **표시만** 한다 |
| `M` / `J` | 전체를 한 방향으로 채운다 (개별 `m`/`j` 로 덮는다) |
| `n` / `p` | 이동 |
| `C-c C-c` | 모든 선택을 **한 번의 `sync`** 로 보낸다 |
| `q` | 닫는다 |

`?` 가 남아 있으면 `C-c C-c` 가 거부하고 그리로 point 를 옮긴다 — 부분 적용이
불가능하다는 것을 UI 가 그대로 반영한다. `M`/`J` + 개별 덮어쓰기는 CLI 의 스코프
우선 규칙과 같은 모양이다.

경로는 페이로드에 없으므로 `mrq-core` 에서 가져온다. `editor.md` §3.4 를 이 내용으로
갱신한다 — 원래의 "키를 누르면 바로 반영" 보다 낫다. 되돌릴 수 있고, 부분 적용 금지가
화면에 보인다.

## 2.10 테스트 하네스와 `make`

### 패키지 격리

`markdown-mode` 를 **사용자의 `~/.emacs.d` 에 설치하지 않는다.**
`plugin_emacs/.elpa/` 를 `package-user-dir` 로 쓰고 `.gitignore` 에 넣는다.
`make deps` 가 거기에 설치하고 `make test-emacs`·`make lint` 가 거기만 본다.
테스트는 전부 `emacs -Q` 다 — 사용자 설정이 결과에 영향을 주지 않는다.

`markdown-mode` 가 없으면 `make test-emacs` 는 **`ert-skip` 하지 않고
"먼저 `make deps`" 로 실패한다.** 조용한 skip 은 깨진 테스트를 숨긴다.

### `mrq-test-helper.el`

`spec/testing.md` §2 의 가짜 `glab` 수법을 그대로 가져온다 — 모킹이 아니라
**진짜 프로세스**다.

- `mrq-test-with-repo` 매크로 — 임시 디렉터리에 `.mrq/<iid>/review.json` +
  `current` 심링크 + 소스 파일을 깔고 정리까지 한다
- **가짜 `mrq` 셸 스크립트** — `mrq-executable` 이 가리킨다. argv 와 stdin 을
  `calls.txt` 에 기록하고, 테스트가 미리 깔아 둔 파일에서 stdout/stderr/종료 코드를
  낸다. 충돌 UI 테스트가 `--prefer a1b2=md --prefer f6e5=json` 이 **정확히 그 인자로**
  갔는지 이 기록으로 확인한다
- `mrq-test-diagnostics` — `flymake-start` 를 동기로 돌리고 진단 리스트를 돌려준다
- `mrq-test-wait-for` — `file-notify` 갱신을 타임아웃과 함께 기다린다.
  **json 을 두 번 이상 연속으로 고쳐** 두 번 다 알림이 오는지 본다

### 테스트 파일

| 파일 | 덮는 것 | 외부 의존 |
|---|---|---|
| `mrq-anchor-test.el` | 적합성 테이블 16건 | 없음 |
| `mrq-core-test.el` | 탐색(심링크/일반 파일), 캐시, watch 두 번, `schema_version` 거부, `current` 가 다른 MR 로 바뀔 때, `.mrq` 생기기 전 버퍼 | 없음 |
| `mrq-schema-test.el` | `testdata/review/*.json` 전부를 실제 리더로 읽고 필수 필드·`enum` 확인 (`repo-layout.md` §4.2) | 없음 |
| `mrq-flymake-test.el` | §2.6 의 다섯 규칙, 같은 줄 중복, `line_end` delta, clamp | 없음 |
| `mrq-cli-test.el` | stdout/stderr 분리, 종료 코드 분기, stdin | 없음 |
| `mrq-conflict-test.el` | 표시·전체채움·미선택 거부, 인자 조립 | 없음 |
| `mrq-mode-test.el` | 헤더 정규식(`(general)` 미매치), 체크박스 순환, `next-error`, 저장 훅 point 복원 | `markdown-mode` |
| `mrq-boundary-test.el` | **메타 테스트** — `mrq-core.el` 밖에 `json-parse` 없음, `mrq-core.el` 에 쓰기 함수 없음 | 없음 |

### `make`

```makefile
test-emacs:   cd plugin_emacs && $(MAKE) test
conformance:  cd plugin_emacs && $(MAKE) conformance
lint:         (기존) + cd plugin_emacs && $(MAKE) lint
deps:         (기존) + cd plugin_emacs && $(MAKE) deps
```

`plugin_emacs/Makefile` 의 `lint` 는 `byte-compile-error-on-warn t` 바이트컴파일 +
`checkdoc`. elisp 에서 가장 싼 방어다 — 오타, 잘못된 인자 수, 쓰이지 않는 변수,
미선언 동적 변수를 전부 여기서 잡는다.

**`make conformance` 는 지금 교차 검증이 아니다** — 구현이 하나뿐이라 elisp 의
회귀 테스트일 뿐이다. 교차 검증은 계획 5 에서 시작된다. 타깃을 지금 만드는 이유는
테이블과 러너의 자리를 계획 5 가 끼워 넣기만 하면 되게 두는 것이고, 루트 `Makefile`
의 안내 메시지를 지우는 것이다.

## 2.11 수락 기준

- `make test` 가 전부 통과하고 `make lint` 가 경고 0
- `make conformance` 가 16건을 통과
- `plugin_emacs/` 가 `editor.md` §1 의 일곱 줄을 지킨다 (메타 테스트로 고정)
- **실측 한 바퀴** — 사용자가 자신의 Emacs 에서 `gitlab.com/jngbng/mr-helper` MR `!1`
  로 체크리스트를 돌린다. 배치 ERT 가 못 잡는 것(다른 flymake 백엔드와의 공존,
  키 바인딩 충돌, 에코 영역 경고의 가시성)이 대상이다

---

## 3. 문서 갱신 목록

| 문서 | 내용 |
|---|---|
| `spec/cli.md` | §1 synopsis, §5 `--prefer` 해소 규칙 + 예시 |
| `spec/data-model.md` | §5.3 해소 수단 |
| `spec/editor.md` | §1 에 "점 이동은 파싱이 아니다", §1-3 호출부 규범 네 줄, §3.4 충돌 UI 재작성 |
| `spec/repo-layout.md` | §4.1 `buffer_set` 포맷, 1-indexed 명시, MUST 범위 축소 |
| `spec/testing.md` | §179 의 `--prefer` 표기 |
| `decisions/0002` | 해소 수단 한 줄 |
| `decisions/0013` | **새 기록** — 해소도 스레드 단위로 섞을 수 있어야 한다 |
| `mrq-design.md` | 변경 없음 (§6 의 "위치 없는 경고" 잠정 항목은 실측 뒤 재평가) |
| `plans/README.md` | 계획 4 전 과제 행 추가, 계획 4 완료 표시 |
