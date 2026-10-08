# 스펙: 데이터 모델

규범 문서. 리포 구조는 `repo-layout.md`에 있다. MUST / SHOULD / MAY는 RFC 2119 의미로 쓴다. 기계 검증 스키마는
`schema/review.schema.json`이며 모든 쓰기 경로 뒤에 이 스키마로 검증해야 한다(MUST).

관련: FR-002, FR-006, FR-018

---

## 1. 리뷰 상태 저장 위치 (FR-018)

```
<repo-root>/.mrq/
  current -> <iid>/        심링크
  <iid>/
    review.json            정본
    review.md              편집면
    lock                   쓰기 락
```

- `<repo-root>`는 `git rev-parse --show-toplevel`이다(MUST). worktree에서는 각
  worktree 루트가 되므로 worktree마다 독립된 리뷰 상태를 갖는다
- `current`는 `<iid>/`를 가리키는 심링크여야 한다(SHOULD). `.mrq/current/review.md`가
  iid를 모르는 소비자(AI 프롬프트, 에디터)의 안정 경로다
- 심링크 생성이 실패하면 `current`를 iid만 담은 텍스트 파일로 쓴다(MAY). 소비자는
  `current`가 디렉터리면 그대로 쓰고, 파일이면 내용을 읽어 한 단계 더 들어간다
- `mrq`는 모든 명령의 시작에서 `.git/info/exclude`에 `/.mrq/`가 있는지 확인하고
  없으면 추가해야 한다(MUST). `.gitignore`는 건드리지 않는다(MUST NOT) — 사용자
  개인 도구의 항목을 팀 리포 히스토리에 넣지 않는다

### 원자성과 락

- `review.json`과 `review.md` 쓰기는 같은 디렉터리의 임시 파일에 쓴 뒤
  `os.replace`로 교체해야 한다(MUST)
- json을 바꾸는 명령은 `lock`을 배타적으로 잡아야 한다(MUST). 에디터의 `sync`와
  터미널의 `push`가 동시에 돌 수 있다. POSIX `flock`(`fcntl.flock`, `LOCK_EX`)을
  쓴다 — 프로세스가 죽어도 커널이 해제하므로 고아 락이 남지 않는다
- 락 획득 실패 시 1초 간격으로 5회 재시도한 뒤 exit 1로 실패한다(SHOULD)

### 손실 복구

`review.md`는 `review.json`에서 완전히 재생성 가능한 파생 상태다. `sync`/`status`/`push`가
md 부재를 감지하면 "md가 없습니다. `mrq pull --render`로 복원하세요"라고 안내하고
json이 온전함을 알려야 한다(MUST).

`review.json`은 복구 불가능한 것(답글 원본, `pushed_hash`, `push_error`)을 들고 있다.
`.mrq/`가 작업 트리에 있으므로 `git clean -fd`에 날아갈 수 있다. 이 위험은 의도적으로
수용한 거래이며 `docs/decisions/0005-storage-location.md`에 기록되어 있다.

---

## 2. 스키마 버전 (FR-018)

`schema_version`은 정수다. 현재 값은 `1`.

| 상황 | 동작 |
|---|---|
| 파일의 버전 == 현재 | 정상 처리 |
| 파일의 버전 > 현재 | **exit 7**, 아무것도 쓰지 않음. "mrq를 업그레이드하세요" |
| 파일의 버전 < 현재 | `pull` 시 마이그레이션. 다른 명령은 exit 7과 함께 `pull`을 안내 |

MVP에는 마이그레이션 구현체가 없다. 거부 경로만 구현한다(MUST).

---

## 3. `review.json`

```jsonc
{
  "schema_version": 1,
  "project": "group/sub/project",
  "iid": 1234,
  "title": "Add retry logic to API client",
  "web_url": "https://gitlab.example.com/.../merge_requests/1234",
  "mr_state": "opened",                  // opened | merged | closed | locked
  "source_branch": "feat/retry",
  "diff_refs": { "base_sha": "...", "start_sha": "...", "head_sha": "abc1234" },

  "me": { "id": 7, "username": "bongya", "can_resolve": true },

  "capabilities": { "draft_notes": true },

  "pulled_at":   "2026-10-11T09:12:00+09:00",
  "rendered_at": "2026-10-11T09:12:01+09:00",

  "threads": [ /* 아래 */ ]
}
```

| 필드 | 쓰는 주체 | 의미 |
|---|---|---|
| `diff_refs` | `pull` | MR의 `versions[0]`에서 가져온다. 재앵커링의 기준 좌표 |
| `me.can_resolve` | `pull` | `projects/:fullpath`의 `permissions.project_access.access_level >= 30` |
| `capabilities.draft_notes` | `pull` | `GET draft_notes` 성공 여부 |
| `pulled_at` | `pull` | 서버 스냅샷을 찍은 시각 |
| `rendered_at` | `pull`/`sync`/`reply`/`state` | `review.md`를 마지막으로 렌더한 시각. **충돌 감지의 기준** |

---

## 4. `threads[]`

```jsonc
{
  "id": "a1b2c3d4e5f6...",        // GitLab discussion id. 모든 참조의 기준 키
  "root_note_id": 5566,           // notes[0].id

  "server": {
    "resolvable": true,
    "resolved": false,
    "repliable": true,
    "updated_at": "2026-10-05T15:30:00+09:00",
    "note_count": 2
  },

  "position": {
    "position_type": "text",      // text | image | file
    "old_path": "src/api/client.py",
    "new_path": "src/api/client.py",
    "old_line": null,
    "new_line": 88,
    "line_range": null
  },

  "anchor": {
    "line": "    resp = session.get(url)",
    "context_before": ["def fetch(url):", "    session = make_session()"],
    "context_after":  ["    return resp.json()"],
    "hunk": "@@ -84,6 +84,9 @@ def fetch(url):\n..."
  },

  "location": {
    "path": "src/api/client.py",
    "line": 102,
    "line_end": null,
    "confidence": "exact",        // exact | fuzzy | stale
    "method": "git-diff"          // git-diff | anchor-search | context-anchor | none
  },

  "notes": [
    { "id": 5566, "author": "jdoe", "created_at": "...", "updated_at": "...",
      "body": "타임아웃 설정이 빠졌습니다.", "mine": false, "suggestions": [] }
  ],

  "local": {
    "state": "todo",              // todo | done | replied | skipped
    "reply": "",
    "touched_at": null,
    "touched_by": null,           // md | cli | push
    "pushed_hash": null,
    "push_error": null
  }
}
```

### 4.1 좌표계를 세 블록으로 분리한다

| 블록 | 좌표계 | 쓰는 주체 | 읽는 주체 |
|---|---|---|---|
| `position` | 서버 diff 좌표 (`diff_refs` 기준) | `pull` | 재앵커링, `push` |
| `anchor` | `head_sha`의 파일 내용 | `pull` | 재앵커링 |
| `location` | **현재 작업 트리** | `pull`/`sync`/`reanchor` | 에디터, 렌더러 |

에디터는 `location`만 읽어야 한다(MUST). `position.new_line`을 위치로 쓰면
안 된다(MUST NOT) — 작업 트리가 이미 바뀌어 있다.

`position`은 GitLab 응답을 변형 없이 보관해야 한다(MUST). `push`가 draft note를
만들 때 그대로 되돌려 보내야 하기 때문이다.

### 4.2 `server.*`는 전부 파생값이다

GitLab의 discussion 객체에는 `{id, individual_note, notes[]}`만 있다. thread 레벨의
`resolved`/`resolvable`/`updated_at`은 **존재하지 않는다.** 다음과 같이 계산한다(MUST).

| 필드 | 계산 |
|---|---|
| `resolvable` | `notes[0].resolvable` |
| `resolved` | `resolvable`한 모든 note가 `resolved == true` |
| `repliable` | `individual_note == false` |
| `updated_at` | `max(notes[].updated_at)` |
| `note_count` | `len(notes)` |

**`notes`는 시스템 노트를 제외한 뒤의 목록이다**(MUST). 필터 전 값을 쓰면 안 된다
(MUST NOT) — 동료가 라벨을 바꾸거나 MR을 재할당한 것만으로 `updated_at`과
`note_count`가 변해, `push`가 멀쩡한 스레드를 "서버에서 변경됨"으로 건너뛴다.

`server.*`는 `pull`만 쓴다(MUST). `sync`/`reply`/`state`는 건드리지 않는다.

`updated_at`과 `note_count`를 **둘 다** 쓰는 이유는 동시 변경 감지(FR-010)의 2차
신호가 필요하기 때문이다. 일부 경로에서 `updated_at`이 갱신되지 않을 수 있다.

### 4.3 `repliable`과 `resolvable`은 1급 제약이다

| 상황 | 동작 |
|---|---|
| `repliable == false` (개별 노트) | `local.reply`를 채워도 `push`가 전송하지 않는다(MUST). `status`가 경고, `review.md`에 `no-reply` 배지. 새 discussion 생성으로 우회하지 않는다(MUST NOT) |
| `resolvable == false` + `state == done` | 로컬 완료로만 처리. 서버 호출 없음, 에러 아님(MUST) |

### 4.4 파일 내용 읽기

`anchor` 추출과 재앵커링에서 파일을 읽을 때:

- `\r\n`을 `\n`으로 정규화한 뒤 비교한다(MUST). CRLF 리포에서 `core.autocrlf`
  설정에 따라 `git show`와 작업 트리의 개행이 달라져 모든 앵커가 어긋난다
- UTF-8로 디코딩할 수 없는 파일은 `confidence: "stale"`, `method: "none"`으로
  둔다(MUST). `location: null`이 아니다 — 텍스트 위치를 가진 코멘트인데 찾지
  못한 것이므로 품질 지표에 드러나야 한다. 예외를 전파해 `pull` 전체를
  실패시키면 안 된다(MUST NOT)

### 4.5 시스템 노트

`system: true`인 노트는 `pull` 단계에서 전량 제외해야 한다(MUST). 라벨 변경·할당·approve
등이 여기로 내려오며, 걸러내지 않으면 노이즈가 절반을 넘는다.

제외 결과 note가 0개가 된 discussion은 스레드로 만들지 않는다(MUST).

### 4.6 `notes[].suggestions`

GitLab 응답의 `suggestions` 배열을 변형 없이 보관해야 한다(MUST). MVP에서는 쓰지
않지만, 버리면 `mrq apply-suggestion`(future work)을 추가할 때 스키마를 깨야 한다.

### 4.7 `local.state`

| 값 | 체크박스 | `push` 동작 |
|---|---|---|
| `todo` | `[ ]` | 아무것도 하지 않음 |
| `done` | `[x]` | `reply`가 있으면 전송 + resolve |
| `replied` | `[~]` | `reply`가 있으면 전송. resolve 안 함 |
| `skipped` | `[-]` | 아무것도 하지 않음 |

`local.*`를 쓰는 주체는 `sync`(md에서), `reply`/`state`(CLI에서), `push`(전송 결과)
세 가지다. 에디터가 직접 쓰면 안 된다(MUST NOT) — `docs/spec/editor.md` 참조.

### 4.8 `local.push_error`

마지막 전송에서 실패한 작업을 기록한다. 성공하면 `null`로 되돌린다(MUST).

```jsonc
{ "op": "resolve",            // reply | resolve
  "status": 403,              // HTTP 상태. 네트워크 실패면 null
  "reason": "forbidden",      // forbidden | not-found | conflict | network | unknown
  "retryable": false,
  "at": "2026-10-11T10:02:00+09:00",
  "message": "403 Forbidden" }
```

`reason`과 `retryable`은 열거값과 불리언이어야 한다(MUST). 소비자가 `message`
문자열을 파싱하게 만들면 안 된다(MUST NOT) — `message`는 사람이 읽는 용도다.

### 4.9 `location` 값의 의미

| `confidence` | 의미 | 진단 표시 |
|---|---|---|
| `exact` | 내용이 `anchor.line`과 완전 일치하고 후보가 유일 | 표시 |
| `fuzzy` | strip 비교·context 점수·context-anchor로 선택 | 표시 + `fuzzy` 배지 |
| `stale` | 텍스트 위치인데 찾지 못함 | **표시하지 않는다**(MUST) |

`stale`을 파일 1행에 붙이면 안 된다(MUST NOT). 그 줄과 무관한 진단이 쌓여 노이즈가
되고, 위치 신뢰를 잃는 가장 빠른 길이다. `review.md`에는 `stale` 배지와 함께 나오고
`status`가 개수를 보고하므로 놓치지 않는다.

`position`이 `null`이거나 `position_type != "text"`이면 **`location`도 `null`**
이다(MUST). `stale`로 표현하면 안 된다(MUST NOT) — "위치를 찾지 못함"과 "위치가
애초에 없음"은 다르고, 섞으면 `stale` 배지가 노이즈가 되어 재앵커링 품질 지표도
오염된다.

`location: null`인 스레드는 재앵커링 통계(`exact`/`fuzzy`/`stale`)에서 제외한다(MUST).
에디터는 진단을 만들지 않는다.

---

## 5. 충돌 감지 (FR-006)

사람은 `review.md`를, AI는 CLI(`mrq reply`/`mrq state`)를 통해 동시에 같은
`review.json`을 바꿀 수 있다. 둘이 **같은 스레드를 서로 다르게** 고친 경우만 충돌이다.
서로 다른 스레드를 고치는 것은 정상 워크플로이며 충돌이 아니다(MUST).

### 5.1 메커니즘

렌더러는 각 스레드의 앵커 주석에 렌더 시점 로컬 상태의 해시를 함께 적는다.

```
<!-- mrq:a1b2c3d4e5f6 v:9f2e3a -->
```

`v` = `sha256(state + "\n" + normalized_reply)`의 앞 **6자**(24비트).

- 반드시 **렌더링된 정규형** 기준으로 계산해야 한다(MUST). 그렇지 않으면 사람이
  손대지 않은 파일을 `sync`해도 전부 "편집됨"으로 잡힌다
- 6자를 쓰는 이유: 충돌 시 "사람이 편집했는데 안 했다고 판정"해서 **조용히 답글이
  사라진다.** 가장 나쁜 실패 양상이므로 1600만 분의 1까지 낮춘다

### 5.2 판정 (`sync`)

스레드별로 세 값을 본다 — md의 현재 값, md의 `v` 토큰, `local.touched_at` vs `rendered_at`.

| md의 값이 `v`와 | 렌더 후 json 변경 | 판정 |
|---|---|---|
| 같다 | 아니오 | **json 유지** |
| 같다 | 예 (`touched_by == "cli"`) | **json 유지** (거짓 충돌 금지) |
| 다르다 | 아니오 | **md 적용** |
| 다르다 | 예 (`touched_by == "cli"`) | **충돌** |
| `v` 토큰 없음 | 아니오 | md 적용 |
| `v` 토큰 없음 | 예 | **충돌** (보수적) |

두 번째 행이 `v` 해시를 도입한 이유다. `touched_at > rendered_at`만 보면 AI가 스레드
1을 고친 직후 사람이 스레드 7만 저장했을 때 스레드 1이 거짓 충돌로 잡힌다.

### 5.3 처리

- 충돌이 **하나라도** 있으면 아무것도 쓰지 않고 **exit 3**으로 끝낸다(MUST)
- 충돌 스레드 목록, 각각의 md 쪽 값과 json 쪽 값을 보고해야 한다(MUST)
- `mrq sync --prefer md|json [--thread ID]...`로 해소한다. `--thread` 없으면 충돌한
  전체, 주면 지정한 것만

---

## 6. 쓰기 주체 요약

| 필드 | `pull` | `sync` | `reanchor` | `reply`/`state` | `push` |
|---|---|---|---|---|---|
| 상단 메타, `diff_refs`, `me`, `capabilities` | ✓ | | | | |
| `pulled_at` | ✓ | | | | |
| `rendered_at` | ✓ | ✓ | ✓ | ✓ | ✓ |
| `server.*` | ✓ | | | | ✓ (재pull 단계) |
| `position`, `anchor` | ✓ | | | | |
| `location` | ✓ | ✓ | ✓ | | |
| `notes[]` | ✓ | | | | |
| `local.state`, `local.reply` | ✓ (새 스레드만) | ✓ | | ✓ | ✓ (reply 비움) |
| `local.touched_*` | | ✓ | | ✓ | ✓ |
| `local.pushed_hash`, `local.push_error` | | | | | ✓ |

`pull`은 기존 `local.*`를 보존해야 한다(MUST) — 같은 스레드 id가 있으면 그대로 두고,
서버에서 사라진 스레드만 제거한다.
