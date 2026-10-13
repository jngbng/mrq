# 스펙: CLI 계약

규범 문서. 관련: FR-001, FR-007 ~ FR-013, FR-016, FR-017

---

## 1. 명령 목록

```
mrq pull     [--mr IID] [--all] [--no-render] [--render]
mrq sync     [--json] [--prefer md|json] [--thread ID]...
mrq status   [--json]
mrq push     [--json] [--dry-run] [--force] [--draft] [--publish]
             [--resolve auto|skip|require]
mrq reanchor [--json]
mrq reply    <thread> (-m MSG | -F FILE | -F -) [--state STATE]
mrq state    <thread> <todo|done|replied|skipped>
mrq list     [--json] [--all] [--state S] [--confidence C]
mrq open     [--mr IID] [--thread ID]
mrq clean    [--merged] [--closed] [--dry-run] [--force]
mrq doctor
```

| 명령 | 네트워크 | git | 쓰기 대상 |
|---|---|---|---|
| `pull` | ✓ | ✓ | json + md |
| `sync` | — | ✓ | json + md 재렌더 |
| `reanchor` | — | ✓ | json + md 재렌더 |
| `status` `list` | — | — | 없음 |
| `reply` `state` | — | — | json + md 재렌더 |
| `push` | ✓ | ✓ (내부 `sync`) | json + md |
| `open` | — | — | 없음 |
| `doctor` | ✓ | ✓ | 없음 |
| `clean` | ✓ (MR 상태 확인) | — | `.mrq/` 디렉터리 제거 |

`reply`와 `state`는 **md를 즉시 재렌더해야 한다**(MUST). AI가 CLI로 상태를 바꾸면
md와 `v:` 해시가 함께 갱신되므로, 사람이 그 뒤에 파일을 열어도 최신 상태를 본다.
거짓 충돌이 생기지 않는다.

`<thread>` 인자는 discussion id의 **유일한 접두사**를 허용해야 한다(MUST). 접두사가
여러 스레드에 걸리면 exit 1과 함께 후보를 보여준다.

---

## 2. 출력 계약

- `--json`일 때 **stdout은 순수 JSON 객체 하나**여야 한다(MUST)
- 경고·진행 로그·에러는 전부 stderr로 보낸다(MUST)

이 규칙이 없으면 에디터와 AI가 출력 앞에 섞인 경고 때문에 파싱에 실패한다.

### 종료 코드

| 코드 | 의미 |
|---|---|
| 0 | 요청한 작업이 모두 성공 (요청하지 않은 작업이 생략된 경우 포함) |
| 1 | 사용법·설정 오류 |
| 2 | `sync` 파싱 에러 — 아무것도 쓰지 않음 |
| 3 | `sync` 충돌 — 아무것도 쓰지 않음 |
| 4 | `push` 부분 실패 |
| 5 | 네트워크·인증 실패 |
| 6 | MR 탐지 실패 (0건 또는 2건 이상) |
| 7 | 스키마 버전 비호환 |

2와 3을 나누는 이유는 에디터가 전혀 다른 UI를 띄워야 하기 때문이다 — 전자는 "md를
고쳐라", 후자는 "어느 쪽을 채택할지 고르라".

`review.json`이 손상된 경우(JSON 문법 오류, 스키마 위반)는 **1**이다 — 전용 코드를
두지 않는다. `editor.md`는 exit 2와 3만 분기하므로 소비자가 생길 때 올린다.
`model.loads`가 `CorruptStateError`로 바꿔 메시지에 `mrq pull`을 안내한다.

### 상태가 없을 때

`.mrq/current`가 없으면 `pull`·`doctor`·`clean`을 제외한 모든 명령은 **exit 1**과
함께 `mrq pull`을 안내해야 한다(MUST). 빈 결과를 성공으로 보고하면 안 된다(MUST
NOT).

`clean`이 예외인 이유는 `current` 한 건이 아니라 `.mrq/` 전체의 저장된 MR
집합을 대상으로 동작하기 때문이다. 제거할 대상이 없는 것은 참인 성공이고, 깨끗한
저장소에서 `mrq clean`을 에러처럼 보이게 만드는 쪽이 스크립트에서 더 나쁘다.

### 체크아웃이 다른 브랜치로 옮겨갔을 때

`.mrq/current`를 무조건 믿으면 `git switch` 뒤에 다른 MR의 리뷰를 보게 된다. 저장된
`source_branch`와 현재 브랜치를 비교해 **읽기는 경고, 쓰기는 거부**해야 한다(MUST).

| 명령 | 동작 |
|---|---|
| `status` `list` | 두 브랜치 이름과 `mrq pull` 안내를 stderr로 경고. 종료 코드는 그대로 |
| `sync` `reply` `state` `reanchor` `push` | **exit 1**, 아무것도 쓰지 않음 |
| `pull` | 자체 탐지(§4 2단계)가 처리하므로 검사하지 않는다 |

읽기를 끊지 않는 이유는 세션 중간에 AI의 읽기 경로를 막는 것이 낡은 상태를 보여주는
것보다 나쁘기 때문이고, 쓰기를 막는 이유는 엉뚱한 MR에 답글을 남기는 것이 실제
손해이기 때문이다. `push`가 그 손해를 실제로 실행하는 명령이므로 가장 앞에서
막혀야 하고, 내부 `sync`가 거부하는 것에 의존하지 않고 **자기 시작점에서**
확인한다. `reanchor`도 쓰기다 — `location`이 재계산 가능하다는 것은 위로가
되지 않는다. 다른 브랜치의 작업 트리로 계산한 위치와 `confidence`가 그럴듯한 틀린
값으로 json에 남아 md와 `status`의 품질 수치에 그대로 나오며, 그것을 덮어쓸 다음
`pull`을 강제하는 장치가 없다. 에디터가 키 한 번으로 부르는 경로라(`editor.md` §3.2)
경고는 읽히지 않고, 어긋난 브랜치에서 `reanchor`를 돌리는 것이 유용한 워크플로도 없다. detached HEAD는 비교할 브랜치 이름이 없으므로 "확인할 수 없음"
경고만 내고 쓰기를 막지 않는다 — 커밋 하나를 체크아웃해 확인하던 사람에게 우회로가
없어진다.

---

## 3. `glab` 위임

인증·호스트 설정·토큰 저장소를 직접 다루지 않는다(MUST NOT). `glab api`에 위임한다.

### 프로젝트 식별

`git remote get-url origin`을 파싱하지 않는다(MUST NOT). `glab api`가 `:fullpath`
플레이스홀더를 체크아웃 기준으로 확장한다.

```sh
glab api "projects/:fullpath/merge_requests?source_branch=feat/retry&state=opened"
```

SSH/HTTPS/커스텀 포트/서브그룹 URL 파싱이라는 실패 지점이 통째로 사라진다.

### 페이지네이션

```sh
glab api "projects/:fullpath/merge_requests/1234/discussions" --paginate --output ndjson
```

줄 단위 JSON이므로 discussion 하나씩 스트리밍 파싱한다.

### 긴 본문 전송

`-F` 값이 `@`로 시작하면 파일, `@-`면 표준 입력이다.

```sh
glab api "projects/:fullpath/merge_requests/1234/discussions/<did>/notes" \
  --method POST -F body=@-
```

답글을 인자로 넘기지 않는다(MUST NOT) — 인자 길이 제한, 셸 인용 문제, 임시 파일이
모두 사라진다. 표와 코드 블록이 섞인 답글을 그대로 보낸다.

### `glab` 기능 확인

버전 번호를 하드코딩하지 않는다(MUST NOT). `doctor`가 이 도구가 의존하는 기능 셋을
직접 확인한다 — `:fullpath` 확장, `--paginate --output ndjson`, `-F key=@-`,
`-i` 가 비2xx 에도 헤더를 내는 것, 그리고 **명시적 `--method GET` 에서 `-f` 가 URL
쿼리가 되는 것**. 마지막 둘은 각각 `push_error.status` 와 MR 탐지가 의존하는
동작이고, glab 이 바꾸면 조용히 틀린 결과가 된다.
버전 문자열은 표시용으로만 쓴다.

### `api()` 의 계약

성공하면 파싱된 JSON, 실패하면 `GlabError` 다. `GlabError` 는 `NetworkError` 를
상속하므로 종료 코드는 5 다.

| 속성 | 값 |
|---|---|
| `status` | HTTP 상태. 읽지 못했으면 `null` |
| `reason` | `forbidden`(403) · `not-found`(404) · `conflict`(409) · `network`(상태 미상) · `unknown` |
| `retryable` | `status` 가 `null` 이거나 5xx 일 때만 참 |

`reason` 과 `retryable` 을 그대로 `local.push_error` 에 쓴다(`data-model.md` §4.8).
상태를 `(status, data)` 튜플로 돌려주지 않는다(MUST NOT) — 상태가 필요한 곳은
실패할 때뿐이고, 튜플은 모든 호출처를 언패킹으로 바꾸면서 **확인을 빼먹어도
조용히 통과하는** 모양을 만든다. 결정
[0010](../decisions/0010-glab-status-via-exception.md) 에 기록되어 있다.

### 쿼리 파라미터

쿼리를 경로 문자열에 보간하면 안 된다(MUST NOT). 브랜치 이름의 `#` 가
프래그먼트로 잘려 **그 뒤의 파라미터까지 통째로 사라진다** — `source_branch` 만
깨지는 것이 아니라 `state=opened` 도 함께 날아가 닫힌 MR 이 후보에 들어온다.

| | 플래그 | 가는 곳 |
|---|---|---|
| `query` | `-f` (`--raw-field`) | URL 쿼리. 값이 전부 문자열이다 |
| `fields` | `-F` (`--field`) | JSON 본문. `resolved=true` 가 불리언이어야 한다 |

`-f` 가 URL 쿼리가 되는 것은 **`--method` 가 명시된 GET/DELETE 에서만**이다.
`--method` 없이 필드를 붙이면 glab 이 요청을 POST 로 바꾼다. `api()` 는 항상
`--method` 를 넘기고, `query` 를 GET/DELETE 가 아닌 메서드에 주면 거부한다(MUST).

### 상태 코드를 읽는 방법

`paginate=False` 일 때 `-i` 를 붙이고 응답 첫 줄(`HTTP/<버전> <코드>`)에서 읽는다.
본문은 **첫** `\r\n\r\n` 뒤부터다 — 본문이 빈 줄을 담고 있어도 잃지 않는다.

**`-i` 는 비2xx 응답에도 헤더 블록을 낸다**(glab 1.114 실측, 404·502 확인).
`GlabError.status` 가 통째로 이 사실 위에 서 있다 — 실패 응답에 헤더가 없다면
상태 코드를 읽을 길이 없고 모든 실패가 `network` 로 접힌다. `-i` 를 떼거나 실패
경로에서 건너뛰는 "최적화" 를 하면 `local.push_error.status` 가 조용히 전부
`null` 이 된다.

바이트 모양도 실측이다 — 상태줄은 `\n` 으로, 헤더는 `\r\n` 으로 끝난다. 파서는
`\n\n` 도 구분자로 받아들여 glab 이 형식을 바꿔도 본문을 잃지 않는다.

**`--paginate` 에는 `-i` 를 붙이지 않는다**(MUST NOT). glab 이 페이지마다 헤더
블록을 내 ndjson 파싱이 깨진다. 그 경로(`pull` 의 discussions)는 상태 코드를 쓰지
않는 유일한 경로이고, 거기서 실패하면 `status` 는 `null`, `reason` 은 `network`
다. `reason` 의 소비자는 `local.push_error` 뿐이고 `push` 는 paginate 를 쓰지
않으므로 틀린 `reason` 이 기록으로 남을 경로가 없다.

### 사용하는 엔드포인트

| 용도 | 호출 |
|---|---|
| MR 탐지 | `GET projects/:fullpath/merge_requests?source_branch=&state=opened` |
| diff_refs | `GET .../merge_requests/:iid/versions` → `[0]` |
| 권한 확인 | `GET projects/:fullpath` → `permissions.project_access.access_level` |
| 내 정보 | `GET user` |
| 스레드 목록 | `GET .../merge_requests/:iid/discussions --paginate --output ndjson` |
| 답글 추가 | `POST .../discussions/:did/notes` (`-F body=@-`) |
| 스레드 resolve | `PUT .../discussions/:did` (`-F resolved=true`) |
| draft 목록 | `GET .../draft_notes` |
| draft 추가 | `POST .../draft_notes` (`note`, `in_reply_to_discussion_id`, `resolve_discussion`) |
| draft 발행 | `POST .../draft_notes/bulk_publish` |

---

## 4. `pull` (FR-001, FR-002)

```
1. .mrq/.gitignore 에 `*` 보장 (없으면)
2. MR 결정:
   a. --mr 지정 → 그것을 쓰고 .mrq/current 갱신
   b. .mrq/current가 있고 그 review.json의 source_branch == 현재 브랜치
      → 그 iid
   c. 현재 브랜치로 조회 → 1건이면 채택하고 current 갱신,
      0건·2건 이상은 exit 6
3. versions[0] → diff_refs
4. GET user, GET projects/:fullpath → me (can_resolve 포함)
5. GET draft_notes → capabilities.draft_notes
6. discussions 전량 조회, system: true 노트 제외
7. head_sha 확보 (필요하면 fetch)
8. anchor 추출 (head_sha의 파일 내용에서)
9. 재앵커링 → location
10. 기존 local.* 보존하며 review.json 쓰기
11. review.md 렌더 (--no-render면 생략)
```

- 리모트는 `origin` 고정이다. fork 워크플로는 범위 밖
- 2건 이상이면 목록을 출력하고 `--mr`로 지정하라고 안내한다(MUST)
- 기존 `local.*`를 덮어쓰면 안 된다(MUST NOT). 응답에서 사라진 스레드는 제거하되,
  미전송 작업(`local.reply`가 비어 있지 않거나 `local.state != todo`)이 있으면
  제거하지 않고 `server.missing = true`로 표시한다. 다시 나타나면 `false`로
  되돌린다 (`data-model.md` §4.10)
- 2b에서 `source_branch`를 확인해야 한다(MUST). 브랜치를 바꿨는데 `current`를 그대로
  쓰면 다른 MR의 상태를 보게 된다
- `--render`는 md만 다시 그린다 (`.mrq/`가 날아간 경우의 복구 경로)

### `--all`은 렌더링에만 영향을 준다

`review.json`은 **항상 모든 스레드를 담는다**(MUST). 서버에서 resolve된 것도
포함한다. `--all`은 `review.md`에 resolve된 스레드까지 그릴지만 결정한다. 따라서
다시 `pull`하지 않고 `mrq pull --render --all`로 전체를 볼 수 있다.

### 미전송 작업이 있는 스레드는 항상 렌더한다

`server.resolved == true`여도 `local.reply`가 비어 있지 않거나 `local.state != todo`인
스레드는 `--all` 없이도 렌더해야 한다(MUST).

동료가 내 스레드를 먼저 resolve하는 일은 흔하다. 기본 렌더가 그 스레드를 숨기면
아직 전송하지 않은 내 답글이 `review.md`에서 사라지고, 사용자는 잃은 줄도 모른다.

---

## 5. `sync` (FR-005, FR-006)

```
1. .mrq/<iid>/review.md 파싱
   - mrq:file 주석의 schema != 현재 → exit 7
   - mrq:file 주석의 iid != 대상 iid → exit 1 ("다른 MR의 review.md입니다")
   - mrq:file 주석의 head != diff_refs.head_sha → 경고 (재앵커링이 처리한다)
   - 파싱 에러 → exit 2, 아무것도 쓰지 않음
2. 스레드별 충돌 판정 (data-model.md §5.2)
   - 충돌 하나라도 → exit 3, 아무것도 쓰지 않음
   - --prefer md|json이 주어지면 해당 방향으로 해소
3. local.state / local.reply 반영, touched_by = "md"
4. 재앵커링 (reanchoring.md)
5. review.json 쓰기, rendered_at 갱신, review.md 재렌더
```

`mrq:file`의 `iid` 검증이 필수다(MUST). 여러 MR을 동시에 다루므로 다른 MR의 md를
잘못된 대상에 sync하면 답글이 엉뚱한 스레드로 들어간다.

`review.md`가 없으면 exit 1과 함께 `mrq pull --render`를 안내한다(MUST).

### 답글이 있는데 `todo`인 스레드

반영 후 `local.reply`가 비어 있지 않은데 `local.state == todo`인 스레드는
**경고해야 한다**(MUST) — `todo`에 대해 `push`는 아무것도 하지 않으므로
(`data-model.md` §4.7) 답글을 쓴 사람은 전송될 것으로 읽는데 실제로는 조용히
남는다. 경고는 알리기만 하고 `push`의 동작도 상태도 바꾸지 않는다(MUST NOT) —
`[ ]`로 두고 초안을 적어 두는 것은 정상 워크플로다. `status`도 같은 이름의 경고를
낸다(§8).

### `sync --json`

페이로드는 **exit 0 · 2 · 3에 대해서만** 정의된다. exit 1(사용법·다른 MR의 md·
브랜치 불일치)과 exit 7(스키마 버전)은 stderr로만 보고한다 — 그 실패들은 리뷰
내용이 아니라 호출 자체가 틀린 경우이고, 소비자가 분기할 것은 종료 코드다.

경고와 에러는 `--json`일 때도 **stderr로 함께** 출력한다(MUST). stdout이 순수 JSON
이기만 하면 §2를 지키는 것이고, 페이로드에만 담으면 사람이 터미널에서 `--json`을
돌렸을 때 아무 메시지도 못 보는 경로가 생긴다. 충돌은 exit 3 전용 UI가 받으므로
`--json`에서는 페이로드로만 보낸다.

exit 0일 때:

```jsonc
{ "iid": 1234,
  "applied": [ { "thread": "a1b2c3d4", "state": "done", "reply_changed": true } ],
  "warnings": [ { "line": 142,  "message": "앵커 다음 줄이 헤더가 아님" },
                { "line": null, "message": "a1b2c3d4: 답글이 있는데 상태가 `[ ]` 입니다 …" } ],
  "anchors": { "exact": 12, "fuzzy": 2, "stale": 1 } }
```

#### `warnings[].line` 은 `null` 일 수 있다

경고가 현재 `review.md` 의 어느 줄에도 걸리지 않을 때 `null` 이다. 지금 그런 경고는
하나다 — 서버에서 resolve 돼 기본 렌더가 생략한 스레드에 `todo` + 답글이 남은 경우
(그 스레드의 블록이 md 에 없다).

**소비자는 위치를 만들어내면 안 된다**(MUST NOT) — `review.md:0` 이나 1행으로
돌리지 않는다. `data-model.md` §4.9 가 `stale` 을 파일 1행에 붙이지 말라고 한 것과
같은 이유다. 위치 없는 경고를 어떻게 보여줄지는 `editor.md` §3.4 에 있다.

**`errors[].line` 은 항상 정수다.** 파싱 에러는 md 의 실제 줄에서만 나오므로
(exit 2 경로), 에디터는 그 UI 에서 위치를 믿고 쓸 수 있다.

exit 3(충돌)일 때 — Emacs의 충돌 버퍼가 이 형식을 소비한다:

```jsonc
{ "iid": 1234,
  "conflicts": [
    { "thread": "a1b2c3d4",
      "md":   { "state": "done",    "reply": "확인했습니다. timeout=10 추가." },
      "json": { "state": "replied", "reply": "AI: 상위에서 설정 중입니다." } }
  ] }
```

exit 2(파싱 에러)일 때:

```jsonc
{ "errors": [ { "line": 88, "message": "체크박스 문자 '?'를 해석할 수 없음" } ] }
```

---

## 6. `reanchor` (FR-003)

`sync`의 4·5단계만 수행한다. md를 파싱하지 않으므로 충돌도 파싱 에러도 발생하지
않는다. `--json`은 `{"anchors": {...}}`만 담는다.

사용자가 소스를 많이 고쳐 위치가 어긋났다고 느낄 때 쓴다.

**네트워크를 쓰지 않는다**(MUST). 이것은 주석이 아니라 강제해야 하는 계약이다 —
`head_sha`가 로컬에 없어도 **fetch를 시도하면 안 된다**(MUST NOT). 커밋이 없으면
문자열 탐색 전용으로 degrade하고, 사용자가 git 매핑을 되찾고 싶으면 `pull`을 돌린다.

이유: `reanchor`를 `pull`과 분리한 유일한 근거가 "로컬이라 자주 돌려도 안전하다"는
것이고, 에디터가 이 경로를 호출한다(`editor.md` §3.2의 `r` 키). 오프라인에서
fetch를 시도하면 TCP 타임아웃만큼 멈추며, 하필 로컬 전용 명령이 가장 필요한
순간에 그렇게 된다. 구현에서는 `ensure_commits(..., allow_fetch=False)`로 막고
테스트로 고정한다.

---

## 7. `list` (FR-007)

AI 에이전트의 읽기 경로다(`editor.md` §5). 사람용 출력은 한 줄 요약의 목록이다.

```
a1b2c3d4  [ ]  src/api/client.py:102  @jdoe   타임아웃 설정이 빠졌습니다…
f6e5d4c3  [~]  src/api/legacy.py:1    @park   `stale`  이건 의도된 동작입니다…
```

`--state`와 `--confidence`로 거른다. `--all`은 서버에서 resolve된 것도 포함한다.

`--all` 없는 기본 보기는 `review-md.md` §5의 예외를 그대로 따른다(MUST) — 서버에서
resolve된 스레드라도 전송하지 않은 작업(`local.reply`가 비어 있지 않거나
`local.state != todo`)이 있으면 보여야 한다. 사람이 보는 `review.md`와 AI가 읽는
`list`가 서로 다른 집합을 보면 안 되기 때문이다.

### `list --json`

`review.json`의 `threads[]`를 **그대로** 내보낸다(MUST). 필드를 가공하거나 줄이지
않는다 — 소비자가 스키마 하나만 알면 되고, `schema/review.schema.json`으로 검증된다.

```jsonc
{ "iid": 1234, "schema_version": 1, "threads": [ /* review.json의 threads[] */ ] }
```

필터(`--state`/`--confidence`/`--all`)는 배열의 원소를 줄이기만 한다.

---

## 8. `status` (FR-007)

```
!1234 Add retry logic to API client  (opened)
head abc1234 · pulled 09:12 · synced 09:40

threads   15 · unresolved 11 · resolved-on-server 4
local     done 8 · replied 3 · skipped 1 · todo 3
anchors   exact 12 · fuzzy 2 · stale 1
push      replies 9 · resolves 8 · skip 1
          ⚠ 7766ccdd 개별 노트라 답글 전송 불가
```

`push` 블록이 **전송 직전 검토면**이다. 30분 예산에서 사용자가 마지막으로 보는
화면이며, "9건 답글 / 8건 resolve"가 기대와 맞는지 확인하는 것으로 충분해야 한다.
`skip`은 전송 대상이지만 **로컬에서 이미 보낼 수 없다고 아는** 스레드의 수다 —
`no-reply`, `not-resolvable`, `server-missing`이 전부다. `todo-with-reply`는
경고일 뿐 전송 대상이 아니므로(`todo`에 `push`는 아무것도 하지 않는다) `skip`에
들어가지 않는다.

### `status`와 `push`는 같은 판정 함수를 쓴다

`push` 블록의 숫자는 `push`의 사전 판정(§9 3단계)과 **같은 함수**에서 나와야
한다(MUST). `status`는 서버 스냅샷 없이, `push --dry-run`은 스냅샷을 들고 같은
함수를 부르므로 두 출력의 차이는 `server-changed` 하나로 한정된다. 함수는
`--resolve` 모드와 `--force`도 입력으로 받으며, `status`는 **기본값**(`auto`,
`--force` 없음)으로 부른다(MUST) — 검토면은 사용자가 플래그 없이 `push`를 쳤을 때
일어날 일을 보여야 한다. 판정을 두 곳에
따로 구현하면 "검토면은 9건이라고 했는데 8건 갔다"가 조용히 생기고, 숫자가 틀리는
순간 검토면 자체가 의미를 잃는다.

`status`는 **오프라인에서 계산할 수 있는 것만** 보고한다(MUST). "pull 이후 서버에서
바뀌었는가"는 네트워크 없이 답할 수 없으므로(§1) 여기서 다루지 않는다 — `server.*`는
`pulled_at`을 기록한 같은 스냅샷이 쓰기 때문에 `server.updated_at > pulled_at`은
구조적으로 거짓이고, 클라이언트 시계가 서버보다 뒤처지면 거짓 참이 되어 보낼 답글을
검토면에서 지워 버린다. 이 판정은 `push`의 재조회 단계(§9 2단계)가 한다.

`threads`/`local`/`anchors`의 수는 `--all` 같은 보기 플래그와 무관하게 `review.json`의
**모든 스레드**를 센다(`review-md.md` §5와 같은 범위).

`me.can_resolve == false`일 때는 push 전에 미리 알려야 한다(MUST).

```
push      replies 9 · resolves 0
          ⚠ resolve 8건: 권한 없음 (access_level 20, Developer 필요) → 전송하지 않음
```

403을 사후에 보고하는 대신 사전에 표시한다. 사용자가 push를 누르고 나서 실패를
발견하는 것이 아니라 검토면에서 먼저 본다.

### `status --json`

```jsonc
{ "iid": 1234, "title": "...", "mr_state": "opened",
  "head_sha": "abc1234", "pulled_at": "...", "rendered_at": "...",
  "threads": { "total": 15, "unresolved": 11, "resolved_on_server": 4 },
  "local":   { "todo": 3, "done": 8, "replied": 3, "skipped": 1 },
  "anchors": { "exact": 12, "fuzzy": 2, "stale": 1 },
  "push":    { "replies": 9, "resolves": 8, "skip": 2 },
  "warnings": [
    { "thread": "7766ccdd", "reason": "no-reply" }
  ] }
```

마지막 `push`에서 실패가 기록된 스레드(`local.push_error != null`)는 `push-failed`
경고로 내야 한다(MUST). `push` 자신의 출력은 그 순간에만 보이므로, 그것이 유일한
표면이면 403과 네트워크 실패가 json 안에만 남는다 — 다음 날 터미널을 다시 연
사람에게는 사라진 것과 같다.

`warnings[].reason`은 열거값이다 — `no-reply`, `not-resolvable`,
`no-resolve-permission`, `mr-not-opened`, `server-missing`, `todo-with-reply`,
`push-failed`. 문자열 메시지를 파싱하게 만들지 않는다(MUST NOT).
`server-changed`는 위 이유로 `status`에 없다 — `push`의 `--dry-run`/`--json`이 쓴다(§9).

---

## 9. `push` (FR-008 ~ FR-011)

```
1. sync 실행 (md → json + 재앵커링). push 가 잡은 락 안에서 수행한다
   에러(2) / 충돌(3)이면 즉시 중단
2. discussions 전체를 한 번 재조회 → 스냅샷
3. 스레드별 사전 판정 (status 와 같은 함수, §8):
   - 스냅샷에 없음 → server-missing 으로 건너뜀
   - server.updated_at 또는 note_count 가 스냅샷과 다름
     → server-changed 로 건너뜀 (--force 로 무시)
   - 내 note 중 body 가 local.reply 와 같음 → 답글을 생략하고 pushed_hash 기록
4. 대상 스레드마다:
   a. repliable && reply != "" && sha256(reply) != pushed_hash
      → POST notes (-F body=@-)
      → 성공 즉시: pushed_hash 기록, local.reply = "", push_error = null,
        touched_by = "push"
   b. state == done && resolvable && !resolved && resolve 요청됨
      → PUT discussions resolved=true
      → 403: push_error 기록, state 를 replied 로 강등, 경고
   c. 스레드 하나가 끝날 때마다 json 을 flush (md 는 그리지 않는다)
5. 락 해제 → pull 재실행 (md 재렌더가 여기서 한 번 일어난다)
```

- 2단계에서 **전체를 한 번만** 조회해야 한다(MUST). 스레드별 GET은 N+1이다
- 1단계의 `sync`는 `push`가 잡은 **같은 락 안에서** 돌아야 한다(MUST). 락을 두 번
  잡으면 그 틈에 에디터의 `sync`가 끼어들어 검토면에서 본 것과 다른 것을 보낸다
- `server-missing`은 `--force`로도 전송하지 않는다(MUST). `--force`가 무시하는 것은
  "서버가 바뀌었다"뿐이고, "서버에 없다"는 보낼 곳이 없는 것이다
  (`data-model.md` §4.10)
- 4a의 `local.reply = ""`가 필수다(MUST). 비우지 않으면 재pull 후 md에 같은 답글이
  인용과 reply 양쪽에 두 번 보인다. `pushed_hash`가 남으므로 재전송되지 않는다
- 4c의 즉시 flush가 필수다(MUST). 중간에 죽어도 재실행으로 복구되어야 한다.
  flush는 **json만** 한다 — md는 5단계의 재pull이 한 번 그린다. 중간에 죽어 md가
  낡아도 거짓 충돌은 생기지 않는다(`data-model.md` §5.2): md의 값은 자기 `v`와
  같으므로 "json 유지"이고, 사람이 그 낡은 md의 답글을 고쳐 `sync`해도
  `pushed_hash`가 재전송을 막는다
- 5단계의 재pull이 실패해도 종료 코드는 **전송 결과를 따른다**(MUST). 전송 결과는
  이미 json에 있고, 그것을 네트워크 실패로 덮으면 사용자가 "안 갔다"로 읽는다.
  재pull 실패는 경고다

### 멱등성 두 겹 (FR-009)

| 순서 | 방어 | 잡는 사망 시점 |
|---|---|---|
| 1 | `sha256(전송 본문) == local.pushed_hash` | POST 성공 + 기록 성공 후 |
| 2 | 스냅샷의 내 note 중 본문이 `local.reply`와 같음 | POST 성공 직후, 기록 **전** |

해시 대상은 **실제로 stdin에 넣은 바이트**다 — `local.reply` 그대로다. 2차 방어의
본문 비교만 양쪽을 `strip()`해 느슨하게 본다(SHOULD). GitLab이 끝 공백을 다듬어
돌려주면 엄격 비교가 중복 전송을 허용하고, 두 실패 양상의 비용이 다르다 — 느슨한
쪽은 전송을 한 번 빼먹고 사용자가 `status`에서 그것을 보지만, 엄격한 쪽은 같은
답글을 두 번 올리고 PRD의 "중복 전송 0건"을 깬다.

2차 방어에 걸렸을 때 `pushed_hash`를 **기록해야 한다**(MUST). 기록하지 않고
건너뛰기만 하면 다음 실행도 매번 스냅샷에 의존하고, 그 note가 스냅샷에서 빠지는
경우(페이지 결손)에 중복 전송으로 되돌아간다.

### 실패 기록 (`local.push_error`)

| 실패 | 기록 | local 상태 | 종료 코드 |
|---|---|---|---|
| reply POST 실패 | `op: "reply"` | `local.reply`를 **비우지 않는다**(MUST) | 4 |
| resolve 403 | `op: "resolve"` | `state`를 `replied`로 강등 | 4 |
| resolve 그 외 실패 | `op: "resolve"` | 상태 유지 | 4 |

`status`·`reason`·`retryable`은 `GlabError`의 값을 그대로 쓴다(§3). 작업이 성공하면
`push_error`를 `null`로 되돌려야 한다(MUST) — 낡은 실패가 남으면 에디터가 이미
해결된 문제를 계속 보여준다.

403에서 `replied`로 강등하는 것이 중요한 이유는 재시도 루프가 상태 기계 차원에서
닫히기 때문이다 — 다음 `push`에서 `replied`는 애초에 resolve 대상이 아니다. 원래
의도는 `push_error`에 남아 잃지 않는다.

### MR이 열려 있지 않을 때

`mr_state != "opened"`면 `push`는 **확인을 요구해야 한다**(MUST). `--force`로 진행한다.
`status`는 `mr-not-opened` 경고를 낸다.

merged된 MR에 답글을 다는 것 자체는 GitLab이 허용하지만, 보통은 브랜치를 바꾼 뒤
`current`가 낡은 것을 가리키고 있다는 신호다.

### `--resolve` (FR-011)

| 값 | 동작 |
|---|---|
| `auto` (기본) | `me.can_resolve`면 시도, 아니면 건너뛰고 경고 |
| `skip` | 시도하지 않는다. 부분 실패가 아니다 |
| `require` | 권한이 없으면 push를 시작하지 않고 exit 1 |

`auto`에서 권한이 없어 생략한 경우는 **exit 0**이다 — 사전에 "전송하지 않음"을
알렸고 실제로 요청하지 않았다. 요청했는데 실패한 것이 아니다.

사전 판정이 틀릴 수 있다(커스텀 역할, 그룹 상속 권한, 내가 작성자인 스레드, MR 잠금).
그 결과 403이 나면 **exit 4**다. 403을 다른 부분 실패와 구분하는 일은 종료 코드가
아니라 `--json` 출력이 담당한다 — 셸 수준에서 403만 따로 분기할 소비자가 없고,
에디터와 AI는 어차피 `--json`을 읽는다.

```jsonc
{
  "pushed": { "replies": 9, "resolves": 0 },
  "failures": [
    { "thread": "a1b2c3d4", "op": "resolve", "status": 403,
      "reason": "forbidden", "retryable": false }
  ]
}
```

`retryable: false`가 에이전트의 재시도 루프를 막는다. state를 `replied`로 강등하면
다음 push에서 그 스레드는 애초에 resolve 대상이 아니므로 루프 위험은 상태 기계
차원에서도 닫힌다. `push_error`에 "done을 의도했으나 403"이 남아 원래 의도도 잃지
않는다.

### `--dry-run`

```
a1b2c3d4  reply(142B) + resolve   src/api/client.py:102
f6e5d4c3  reply(88B)              src/api/legacy.py:1    `stale`
9988aabb  resolve                 src/util.py:12
7766ccdd  skip  no-reply          (general)
5544eeff  skip  server-changed    src/api/client.py:60
3322bbaa  skip  server-missing    src/api/old.py:9
```

`skip` 이유는 열거값이며 `--json`과 같은 값을 쓴다(MUST) — `no-reply` ·
`not-resolvable` · `no-resolve-permission` · `server-changed` · `server-missing`.
문자열 메시지를 파싱하게 만들지 않는다(MUST NOT).

### `--draft` (FR-013)

`POST draft_notes`는 `in_reply_to_discussion_id`와 `resolve_discussion`을 함께 받는다.
따라서 답글과 resolve를 하나의 draft로 묶고, `--publish`가 `bulk_publish`로 일괄
발행한다. 리뷰 한 라운드를 통째로 묶어 보낼 수 있다.

대상 판정은 일반 경로와 **같은 함수**를 쓴다(§8). 다른 것은 전송 방법뿐이다.

`capabilities.draft_notes == false`면 `--draft`를 **명확한 메시지와 함께 거부해야
한다**(MUST). 조용히 일반 notes 경로로 빠지면 안 된다(MUST NOT) — 사용자는 draft로
갔다고 믿는다. 이 확인은 `--resolve require`의 권한 확인과 **같은 자리**(sync·락보다
앞)에서 한다 — `capabilities`도 sync가 건드리는 필드가 아니므로 디스크 값을 그대로
읽어도 되고, "push를 시작하지 않고 exit 1"이 글자 그대로 맞으려면 락 전에 끊어야
한다.

**draft 생성은 전송이 아니다.** 따라서 생성 시점에 `pushed_hash`를 기록하지 않고
`local.reply`도 비우지 않는다(MUST NOT) — 발행하지 않으면 그 답글은 GitLab의 내
draft 안에만 있고, 로컬에서 지우면 사용자가 자기 글을 잃는다. 둘은 **발행 시점에만**
갱신한다. 근거는
[0012](../decisions/0012-draft-is-not-a-send.md)에 있다.

| 단계 | 동작 |
|---|---|
| 1 | `GET draft_notes` 한 번 → `(discussion_id, note)` 집합 |
| 2 | 집합에 같은 쌍이 있으면 생성을 생략 |
| 3 | `POST draft_notes` — `note`, `in_reply_to_discussion_id`, 그리고 resolve 요청이면 `resolve_discussion: true` |
| 4 | `--publish`면 `POST bulk_publish` 한 번 → 발행 직전 목록을 근거로 `pushed_hash` 기록 + `local.reply` 정리 |

- 4단계에서 기록하는 `pushed_hash`는 **발행된 draft 본문**의 해시다. 그리고
  `local.reply`는 그 본문과 **현재 값이 같을 때만** 비운다(MUST) — draft를 만든 뒤
  사용자가 md에서 답글을 고쳤다면 비우는 것이 그 수정을 지운다. 다르면 해시만
  기록하고 답글은 남긴다. 해시가 다르므로 다음 `push`가 새 본문을 정상 전송한다
- **`--publish` 단독은 1·2단계(`sync`·스냅샷)를 생략한다.** 발행할 draft는 이미
  있고 대상 판정이 필요 없다. 발행은 서버에 이미 있는 draft를 내보내는 일이라
  로컬 `review.md`와 무관하다 — `review.md`에 파싱 에러나 충돌이 있어도 이미
  사용자 손을 떠난 draft를 발행하지 못하게 막으면 안 된다. 4단계의 json 갱신과
  5단계의 재pull은 그대로 한다
- **5단계의 재pull은 `--publish` 단독일 때 md를 다시 그리지 않는다**(MUST,
  `pull --no-render`와 같은 경로). 1·2단계를 생략했으므로 로컬 `review.md`에
  아직 `sync`되지 않은 사용자의 수정이 남아 있을 수 있다 — md를 덮어쓰면 그
  수정이 흔적 없이 사라진다(결정 0012가 막으려는 것과 같은 손실). md를 그대로
  두면 다음 `sync`가 그 수정을 받아들인다 — 발행된 draft의 `touched_by`는
  `"push"`이므로(`data-model.md` §5.2) 그다음 `sync`는 이것을 충돌이 아니라
  "md 적용"으로 판정하고, `pushed_hash`는 발행된(옛) 본문의 해시라 사용자의 새
  본문과 달라 다음 `push`가 그 새 본문을 정상 전송한다
- draft 생성 실패와 발행 실패는 `push_error`에 `op: "draft"` / `op: "publish"`로
  기록하고 **exit 4**다. 일반 경로의 부분 실패와 같은 취급이다
- **발행 실패는 스레드 하나의 일이 아니다**(MUST) — `bulk_publish`는 선택적
  발행이 없는 MR 전체 단위 호출이므로, 실패하면 이번에 발행하려던 **내 draft
  전부**의 스레드에 `push_error{op: "publish"}`를 기록한다. 임의로 스레드
  하나에만 떠넘기지 않는다
- 1단계가 **중복 방어 전부**다(MUST). `pushed_hash`가 아직 없으므로 두 겹이 아니다.
  그래서 이 조회가 실패하면 draft를 만들지 않는다(MUST) — 방어 없이 만들면
  재실행이 draft를 복제하고, 사용자는 GitLab UI에서 그것을 손으로 지워야 한다
- 중복 방어의 키는 `(discussion_id, body)`뿐이다 — `resolve_discussion`은 보지
  않는다. 그래서 답글 본문은 그대로인데 새로 resolve가 필요해진 스레드는 이미
  있는(resolve 없는) draft에 가로막혀 조용히 생략될 수 있다. draft 수정은
  범위 밖이므로(아래) 고치지 못하고, 스레드를 대고 경고한다("GitLab UI에서
  지우고 다시 만드세요")
- resolve는 `resolve_discussion`으로 draft에 묶는다. 별도 `PUT discussions`를
  보내지 않는다(MUST NOT). 권한이 없으면 `false`로 보내고 경고한다 — `--resolve`
  표의 `auto` 행과 같은 판정이다
- **답글이 없는(resolve-only) 스레드는 `--draft`에서 건너뛴다**(MUST) — `POST
  draft_notes`의 `note`는 필수라 빈 본문은 GitLab이 거부하거나(400), 받아들이면
  빈 note가 실제로 생긴다. resolve만 즉시 반영하는 별도 `PUT discussions`도 위
  규칙으로 금지되어 있으므로(MUST NOT) draft 경로로는 resolve만 표현할 방법이
  없다. 건너뛸 때 스레드를 이름으로 짚고 일반 `mrq push`로 안내해야 한다(MUST)
  — 그 경로는 resolve만 정상적으로 보낸다. 근거는
  [0012](../decisions/0012-draft-is-not-a-send.md)에 있다
- `--draft --publish`(묶어 보내고 즉시 발행)와 `--publish` 단독(지난 draft 발행)을
  모두 허용한다
- draft 수정·삭제(`PUT`/`DELETE draft_notes`)는 범위 밖이다. 잘못 만든 draft는
  GitLab UI에서 지운다
- **`pushed.replies`/`pushed.resolves`는 실제로 나간 것만 센다**(MUST). draft
  생성 단독은 전송이 아니므로(결정 0012) 둘 다 `0`이고, 사람이 읽는 줄은 대신
  만들어진(또는 이미 있던) draft 수를 말한다. `--publish`가 수행되면 그 수는
  **발행된 draft 중 "내" 것**(아래 foreign 판정 참조)의 수이고, `resolves`는
  그중 `resolve_discussion`을 담고 있던 것의 수다 — `push.plan`의 판정(일반
  경로의 미리보기용)과 더 이상 섞이지 않는다
- **`--dry-run --draft`**는 통상의 미리보기 행 각각을 draft로 묶일 것으로
  표시한다("draft reply(…)" 등) — 그대로 두면 "보냈다"로 읽혀 draft는 전송이
  아니라는 결정 0012와 어긋난다. **`--dry-run --publish`**(단독)는 통상의
  미리보기를 쓰지 않는다 — 그 경로의 `sheet`는 스냅샷 없이 만들어져
  `server-changed`를 보여줄 수 없고, 보여줄 것은 애초에 "이번에 보낼 것"이
  아니라 "이미 서버에 있는 draft"다. 대신 `GET draft_notes`로 실제 발행
  대상을 조회해(쓰지 않는다) 목록과 ours/foreign 수를 보여준다

#### `bulk_publish`는 내 draft 전부를 발행한다

`bulk_publish`에는 "이것만 발행" 파라미터가 없다. 따라서 사용자가 GitLab UI에서
쓰던 미완성 draft까지 함께 공개된다. `--publish`는 1단계 목록에 **mrq가 만들지
않은(foreign) draft**가 있으면 그 수를 보여주고 **확인을 요구해야 한다**(MUST).
`--force`로 진행한다.

**foreign 판정은 `discussion_id`만 본다** — 그 값이 이 리뷰의 어느 스레드 id와도
같지 않으면(UI에서 새로 시작한 미완성 리뷰처럼 `discussion_id`가 없는 경우를
포함) foreign이고, 같으면 ours다. body(note) 비교는 여기 쓰지 않는다 — 발행
시점에 `local.reply`를 비울지 정하는 데만 쓴다(위 4단계). body로 판정하면 draft를
만든 뒤 사용자가 md에서 답글을 고친 **자기 자신의 draft**를 foreign으로 잘못 보고
불필요한 확인을 요구한다.

받아들이는 결과: GitLab UI에서 **mrq가 추적하는 스레드 위에** 만들어진 draft는
discussion_id가 일치하므로 ours로 분류되어 확인 없이 함께 발행되고, 그 본문이
그 스레드의 `local.reply`를 비울 수 있다. 이것은 의도한 결과다 — `bulk_publish`가
선택적 발행을 지원하지 않으므로 그 draft는 어차피 같이 나간다(ours로 분류하든
안 하든 결과는 같다), 그리고 그것은 **같은 스레드의 같은 리뷰 라운드**이지 전혀
남의 작업이 아니다. 확인이 막아야 하는 것은 "내가 모르는 별개의 작업이 같이
나가는 것"(foreign)이고, 이 경우는 그게 아니다.

`mr_state != "opened"`에 확인을 요구하는 것과 같은 이유다 — 바깥으로 나가고
되돌릴 수 없다.

---

## 10. `reply` / `state` (FR-012)

```sh
mrq reply a1b2 -m "확인했습니다"
mrq reply a1b2 -F - --state done     # stdin에서 본문을 읽는다
mrq state a1b2 done
```

- json의 `local.*`를 갱신하고 `touched_by = "cli"`, `touched_at = now`를 기록한다(MUST)
- `rendered_at`을 갱신하고 md를 재렌더해야 한다(MUST)
- VSCode CodeLens와 AI 에이전트가 쓰는 경로다. 이들은 md를 파싱하지 않는다

---

## 11. `clean` (FR-017)

`.mrq/<iid>/`를 제거한다. 대상은 MR 상태로 판정한다.

- `--merged` / `--closed`로 대상을 고른다. 둘 다 없으면 둘 다
- `local.reply`가 비어 있지 않거나 `state != todo`인 스레드가 있으면 **확인을
  요구해야 한다**(MUST) — 전송하지 않은 작업이 남아 있다. 이 판정은 일부러
  보수적이다 — 이미 push된 스레드(`done`/`replied`로 남아 있지만 재전송할
  내용은 없는 경우)도 "미전송 작업"으로 센다. 틀린 방향이 안전한 방향이므로
  더 정밀하게 고치지 않는다
- `--dry-run`으로 대상만 출력
- `--force`로 위 확인을 건너뛴다 (`prompt.confirm`과 같은 규칙, `push`의
  `--force`와 동일한 의미)

---

- `current`가 가리키는 MR을 제거하면 `current`도 함께 제거해야 한다(MUST).
  끊어진 심링크를 남기지 않는다

---

## 12. `open` (FR-019)

브라우저로 MR 또는 특정 스레드를 연다.

```sh
mrq open                  # MR 페이지
mrq open --thread a1b2    # 해당 discussion 앵커로 이동
```

`web_url`을 쓰고, `--thread`면 `#note_<root_note_id>`를 붙인다. 브라우저 실행은
`webbrowser.open`에 맡긴다.

GitLab UI에서 확인해야 하는 경우(이미지 코멘트, 개별 노트, 리뷰어와의 긴 논의)가
있으므로 왕복 비용을 줄이는 용도다.

---

## 13. `doctor` (FR-016)

```
$ mrq doctor
glab          ✓ v1.58.0
glab auth     ✓ bongya (id 42)
remote        ✓ origin → group/sub/project
MR            ✓ !1234 (source_branch feat/retry)
head_sha      ✓ abc1234 (로컬에 있음)
discussions   ✓ --paginate --output ndjson 동작
stdin         ✓ -F text=@- 동작
draft_notes   ✓ 사용 가능
resolve 권한  ✓ Developer 이상
storage       ✓ /home/bongya/w/proj/.mrq
```

`discussions`는 `pull`이 의존하는 `--paginate --output ndjson` 경로를 실제로 한 번
태워 확인하고, `stdin`은 `reply`/`push`가 답글 본문을 보내는 `-F field=@-` 경로를
부작용 없는 호출(`POST /markdown`)로 확인한다. 이 인스턴스가 그 엔드포인트를
지원하지 않거나 권한이 없으면(403/404) `stdin`은 거짓 `✗` 대신 "확인 불가"를
보고한다. `.mrq/.gitignore` 확인은 별도 행이 아니라 `storage`에 합쳐져 있다 — 없으면
`storage`가 `✗`와 함께 그것을 알린다.

`doctor`는 `.mrq/`를 **만들지 않는다**(MUST NOT) — `.mrq/.gitignore` 보장은 다른
모든 명령의 시작 규칙이지만(`data-model.md` §1), 진단이 상태를 만들면 "없음"을
진단할 수 없다. 현재 상태를 그대로 보고한다. `.mrq/`가 없는 저장소에서도 끝까지
돌아야 한다(MUST).

실패한 항목은 `✗`와 함께 다음에 할 일을 적어야 한다(MUST). 범위가 개인/단일
인스턴스이므로 환경 문제는 전부 한 머신에서 발생한다. 설정 실패를 추측하게 만들지
않는 것만으로 충분하다.
