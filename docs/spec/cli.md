# 스펙: CLI 계약

규범 문서. 관련: FR-001, FR-007 ~ FR-013, FR-016, FR-017

---

## 1. 명령 목록

```
mrq pull     [--mr IID] [--all] [--no-render] [--render]
mrq sync     [--json] [--prefer md|json] [--thread ID]...
mrq status   [--json]
mrq push     [--dry-run] [--force] [--draft] [--publish]
             [--resolve auto|skip|require]
mrq reanchor [--json]
mrq reply    <thread> (-m MSG | -F FILE | -F -) [--state STATE]
mrq state    <thread> <todo|done|replied|skipped>
mrq list     [--json] [--all] [--state S] [--confidence C]
mrq open     [--mr IID] [--thread ID]
mrq clean    [--merged] [--closed] [--dry-run]
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
| `open` `doctor` | ✓ | — | 없음 |
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

### 상태가 없을 때

`.mrq/current`가 없으면 `pull`과 `doctor`를 제외한 모든 명령은 **exit 1**과 함께
`mrq pull`을 안내해야 한다(MUST). 빈 결과를 성공으로 보고하면 안 된다(MUST NOT).

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
직접 확인한다 — `:fullpath` 확장, `--paginate --output ndjson`, `-F key=@-`.
버전 문자열은 표시용으로만 쓴다.

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
1. .git/info/exclude에 /.mrq/ 등록 (없으면)
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
- 기존 `local.*`를 덮어쓰면 안 된다(MUST NOT). 서버에서 사라진 스레드만 제거한다
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

### `sync --json`

exit 0일 때:

```jsonc
{ "iid": 1234,
  "applied": [ { "thread": "a1b2c3d4", "state": "done", "reply_changed": true } ],
  "warnings": [ { "line": 142, "message": "앵커 다음 줄이 헤더가 아님" } ],
  "anchors": { "exact": 12, "fuzzy": 2, "stale": 1 } }
```

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

사용자가 소스를 많이 고쳐 위치가 어긋났다고 느낄 때 쓴다. 네트워크를 쓰지 않는다.

---

## 7. `list` (FR-007)

AI 에이전트의 읽기 경로다(`editor.md` §5). 사람용 출력은 한 줄 요약의 목록이다.

```
a1b2c3d4  [ ]  src/api/client.py:102  @jdoe   타임아웃 설정이 빠졌습니다…
f6e5d4c3  [~]  src/api/legacy.py:1    @park   `stale`  이건 의도된 동작입니다…
```

`--state`와 `--confidence`로 거른다. `--all`은 서버에서 resolve된 것도 포함한다.

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
push      replies 9 · resolves 8 · skip 2
          ⚠ f6e5d4c3 서버에서 변경됨 (pull 이후) — 건너뜀, --force로 무시
          ⚠ 7766ccdd 개별 노트라 답글 전송 불가
```

`push` 블록이 **전송 직전 검토면**이다. 30분 예산에서 사용자가 마지막으로 보는
화면이며, "9건 답글 / 8건 resolve"가 기대와 맞는지 확인하는 것으로 충분해야 한다.

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
    { "thread": "f6e5d4c3", "reason": "server-changed" },
    { "thread": "7766ccdd", "reason": "no-reply" }
  ] }
```

`warnings[].reason`은 열거값이다 — `server-changed`, `no-reply`, `not-resolvable`,
`no-resolve-permission`, `mr-not-opened`. 문자열 메시지를 파싱하게 만들지 않는다(MUST NOT).

---

## 9. `push` (FR-008 ~ FR-011)

```
1. sync 실행 (md → json + 재앵커링)
   에러(2) / 충돌(3)이면 즉시 중단
2. discussions 전체를 한 번 재조회 → 스냅샷
3. 스레드별 사전 판정:
   - server.updated_at 또는 note_count가 pulled 시점과 다름 → 건너뜀
     (--force로 무시)
   - 내 note 중 body가 local.reply와 동일한 것이 이미 있음 → 답글 생략
4. 대상 스레드마다:
   a. repliable && reply != "" && sha256(reply) != pushed_hash
      → POST notes (-F body=@-)
      → 성공 즉시: pushed_hash 기록, local.reply = "", touched_by = "push"
   b. state == done && resolvable && !resolved && resolve 요청됨
      → PUT discussions resolved=true
      → 403: push_error 기록, state를 replied로 강등, 경고
   c. 스레드 하나가 끝날 때마다 json을 flush
5. pull 재실행
```

- 2단계에서 **전체를 한 번만** 조회해야 한다(MUST). 스레드별 GET은 N+1이다
- 3단계의 "동일 본문 체크"는 `pushed_hash`와 이중 방어다. `pushed_hash` 기록
  직전에 프로세스가 죽은 경우를 잡는다
- 4a의 `local.reply = ""`가 필수다(MUST). 비우지 않으면 재pull 후 md에 같은 답글이
  인용과 reply 양쪽에 두 번 보인다. `pushed_hash`가 남으므로 재전송되지 않는다
- 4c의 즉시 flush가 필수다(MUST). 중간에 죽어도 재실행으로 복구되어야 한다

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
```

### `--draft` (FR-013)

`POST draft_notes`는 `in_reply_to_discussion_id`와 `resolve_discussion`을 함께 받는다.
따라서 답글과 resolve를 하나의 draft로 묶고, `--publish`가 `bulk_publish`로 일괄
발행한다. 리뷰 한 라운드를 통째로 묶어 보낼 수 있다.

`capabilities.draft_notes == false`면 `--draft`를 **명확한 메시지와 함께 거부해야
한다**(MUST). 조용히 일반 notes 경로로 빠지면 안 된다(MUST NOT) — 사용자는 draft로
갔다고 믿는다.

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
  요구해야 한다**(MUST) — 전송하지 않은 작업이 남아 있다
- `--dry-run`으로 대상만 출력

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
glab auth     ✓ gitlab.example.com (bongya)
remote        ✓ origin → group/sub/project
MR            ✓ !1234 (source_branch feat/retry)
head_sha      ✓ abc1234 (로컬에 있음)
draft_notes   ✓ 사용 가능
resolve 권한  ✓ access_level 40
storage       ✓ /home/bongya/w/proj/.mrq
git exclude   ✓ /.mrq/ 등록됨
```

실패한 항목은 `✗`와 함께 다음에 할 일을 적어야 한다(MUST). 범위가 개인/단일
인스턴스이므로 환경 문제는 전부 한 머신에서 발생한다. 설정 실패를 추측하게 만들지
않는 것만으로 충분하다.
