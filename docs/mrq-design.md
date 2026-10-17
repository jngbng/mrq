# mrq 설계 문서

GitLab MR의 리뷰 코멘트를 로컬 파일로 내려받아, 에디터(Emacs/VSCode)와 AI 에이전트가
동일한 방식으로 읽고 답글을 작성한 뒤 다시 GitLab에 반영하는 도구.

이 문서는 **아키텍처와 근거**를 다룬다. 규범적 정의는 스펙 문서에 있고, 충돌하면
스펙이 우선이다.

| 문서 | 내용 |
|---|---|
| `PRD.md` | 목적·성공 기준·시나리오·기능 목록(FR ID) |
| `spec/data-model.md` | `review.json` 스키마, 저장소 레이아웃, 충돌 감지 |
| `spec/reanchoring.md` | 위치 재계산 알고리즘 — 품질을 좌우하는 부분 |
| `spec/review-md.md` | 편집면 문법, 파싱, 에러 분류 |
| `spec/cli.md` | 명령 계약, 종료 코드, `glab` 위임 |
| `spec/editor.md` | 에디터 플러그인의 역할 경계 |
| `spec/testing.md` | 공통 테스트 인프라 |
| `spec/repo-layout.md` | 리포 구조, 하위 프로젝트 툴체인, 적합성 테이블 |
| `decisions/` | 주요 갈림길의 선택과 근거 |
| `plans/README.md` | **구현 순서와 계획 1~5 로드맵.** 단계·FR 매핑, 범위, 시작 조건 |
| `plans/` | 진행 중인 계획서와 잔여 항목 |
| `schema/review.schema.json` | 기계 검증용 |

---

## 1. 설계 원칙

**1. 네트워크와 git 접근은 CLI만.** 인증·API·재시도·`git diff`는 전부 파이썬
CLI(`mrq`)가 담당한다. 에디터 플러그인은 `review.json`을 읽고 CLI를 호출한다. 이 분리
덕분에 Emacs 플러그인과 VSCode 확장이 같은 데이터를 보고, AI 에이전트도 별도 도구 없이
참여한다.

예외는 하나뿐이다 — 에디터는 버퍼에서 앵커 한 줄을 찾는 단순 검색을
할 수 있다(저장 여부를 보지 않는다). 범위는 `spec/reanchoring.md` §6에 규범으로 묶여 있다 ([0003](decisions/0003-split-reanchoring-responsibility.md)).

**2. 정본은 JSON, 편집면은 Markdown.** `review.json`이 유일한 진실원천이다.
`review.md`는 사람과 AI가 편집하는 표면이며, 파싱에 실패해도 json은 온전하므로 상태가
통째로 날아가지 않는다. md는 json에서 완전히 재생성 가능한 파생 상태다.

**3. 전송과 병합을 분리.** `sync`(md → json, 네트워크 없음)와 `push`(json → GitLab)를
나눈다. "체크만 해두고 아직 안 올린 상태"가 반드시 필요하다.

**4. 파싱은 위치가 아니라 앵커 기준.** `review.md` 안의 `<!-- mrq:ID v:HASH -->` 주석으로
스레드를 식별한다. AI가 섹션 순서를 바꾸거나 메모를 끼워 넣어도 깨지지 않는다.

**5. 사람과 AI는 대등하다.** 어느 쪽도 부차적 경로가 아니다. 둘이 동시에 작업하는 것이
정상이며, 같은 스레드를 서로 다르게 고친 경우만 충돌이다 ([0001](decisions/0001-human-and-ai-are-peers.md), [0002](decisions/0002-per-thread-conflict-detection.md)).

---

## 2. 구성 요소

```
          ┌─────────────┐
          │  GitLab API │
          └──────┬──────┘
                 │ glab api  (인증·호스트 설정 위임)
          ┌──────┴──────┐
          │  mrq (CLI)  │──── git diff (재앵커링)
          └──────┬──────┘
                 │ 파일만
     ┌───────────┼───────────┐
     │           │           │
  review.json  review.md   .mrq/current
     │           │
  ┌──┴──┐    ┌───┴────┐
  │에디터│    │사람/AI │
  └─────┘    └────────┘
```

| 단위 | 하는 일 | 의존 |
|---|---|---|
| `pull` | GitLab 조회 → json 생성, 재앵커링, md 렌더 | `glab`, `git` |
| 재앵커링 | `head_sha` 좌표 → 작업 트리 좌표 | `git` |
| 렌더러 | json → md | — |
| 파서 | md → json의 `local.*` | — |
| `push` | json → GitLab, 결과를 json에 기록 | `glab` |
| `mrq.el` | 진단 표시, 목록 버퍼, CLI 호출 | `review.json` |
| VSCode 확장 | 진단 표시, CodeLens, CLI 호출 | `review.json` |

파서와 렌더러는 Python에만 존재한다. 에디터는 md를 파싱하지 않는다 — 세 곳에 두면
셋이 미묘하게 달라지고, 그 차이가 사용자의 답글을 잃는 형태로 나타난다.

하위 프로젝트는 셋이며 한 리포에서 관리한다 — `cli/`(Python), `plugin_emacs/`(elisp),
`plugin_vscode/`(TypeScript). 셋이 공유하는 계약(`schema/`, `testdata/`)과 그 계약의
drift를 막는 적합성 테이블은 `spec/repo-layout.md`에 있다.

---

## 3. 저장소 레이아웃

```
<repo-root>/.mrq/
  .gitignore
  current -> <iid>/
  <iid>/{review.json, review.md, lock}
```

리포 루트의 `.mrq/`에 둔다. `mrq`가 `.mrq/.gitignore`에 `*`를 쓰므로 사용자가 할 일은
없고, 리포 루트의 `.gitignore`를 건드리지 않으므로 개인 도구의 항목이 팀 리포
히스토리에 섞이지 않는다. `.git/` 아래에는 쓰지 않는다
([0007](decisions/0007-mrq-gitignore.md)).

`.git/` 아래가 아닌 이유와 그 대가로 수용한 `git clean` 위험은 [0005](decisions/0005-storage-location.md)에 있다.

MR iid별로 디렉터리를 나눠 여러 MR을 동시에 다룬다. worktree마다 독립적인 상태를 갖는다.

---

## 4. 데이터 흐름

```
GitLab ──pull──> review.json ──render──> review.md
                      ↑                      │
                      │                   사람/AI 편집
                      │                      │
                      └────── sync ──────────┘
                      ↑
                 reply / state (CLI)
                      │
                      └──push──> GitLab
```

`sync`는 md 반영과 재앵커링을 함께 수행한다. 에디터 저장 훅이 `sync` 하나만 호출하면
끝나고, 둘이 따로 돌아 중간 상태가 보이는 일이 없다.

`push`는 내부적으로 `sync`를 먼저 돌리고, 끝나면 `pull`을 다시 돌린다.

---

## 5. 반드시 처리할 함정

### 5.1 라인 드리프트 (가장 중요)

코멘트의 `position`은 MR의 `head_sha` 기준인데 로컬 작업 트리는 이미 수정된 상태다.
그대로 쓰면 엉뚱한 줄에 진단이 붙어 즉시 신뢰를 잃는다.

핵심은 **git이 정답을 이미 알고 있다**는 것이다. `git diff -M -U0 <head_sha> -- <path>`의
hunk 헤더로 라인 맵을 만들면 정확하고, 문자열 탐색은 그것이 실패했을 때의 fallback이다.
`head_sha`가 로컬에 없으면 `refs/merge-requests/<iid>/head`를 fetch한다 — 이 단계가
없으면 재앵커링 전체가 동작하지 않는다.

알고리즘 전체는 `spec/reanchoring.md`에 있다. 품질 목표는 `exact ≥ 75%`,
`stale ≤ 10%`이며 회귀 테스트로 강제한다.

위치를 찾지 못한 것(`stale`)에는 **진단을 띄우지 않는다.** 파일 1행에 몰아두는 것이
위치 신뢰를 잃는 가장 빠른 길이다 — `review.md`의 배지와 `status`의 수치가 그것을
알리는 면이다 (`spec/data-model.md` §4.9).

### 5.2 중복 전송

`push` 직후 네트워크가 끊기거나 사용자가 두 번 실행하면 답글이 두 번 올라간다.
답글 본문의 sha256을 `local.pushed_hash`에 기록하고 같으면 건너뛴다. 추가로 `push`
시작 시 받은 서버 스냅샷에서 "내 note 중 같은 본문이 이미 있는지"를 확인해 이중으로
막는다 — `pushed_hash` 기록 직전에 죽은 경우를 잡는다.

전송에 성공하면 `local.reply`를 비운다. 비우지 않으면 재pull 후 같은 답글이 md에
인용과 reply 양쪽으로 두 번 보인다.

전송 결과는 **스레드마다 즉시 json에 쓴다**. 중간에 죽어도 재실행이 남은 것부터
이어가야 하고, 그 보장이 병렬 전송과 같이 갈 수 없다는 것이 지금의 순차 구조다
(`spec/cli.md` §9).

### 5.3 동시 변경

작업하는 동안 동료가 같은 스레드에 답글을 달 수 있다. `push` 시작 시 discussions를
**한 번만** 전체 재조회해 스냅샷을 만들고, `server.updated_at` 또는 `note_count`가
pull 때와 다른 스레드는 건너뛴다. `--force`로 무시할 수 있다.

스레드별로 GET을 날리면 N+1이다. 전체를 한 번 받는다.

### 5.4 resolve 권한

GitLab에서 스레드 resolve는 작성자 또는 Developer 이상만 가능하다. 이를 **사후 에러가
아니라 사전 표시**로 다룬다 — `pull`이 `permissions.project_access.access_level`을
받아 `me.can_resolve`에 기록하고, `status`가 push 전에 "resolve 8건: 권한 없음 →
전송하지 않음"을 보여준다.

그래도 403이 나오면(커스텀 역할, 그룹 상속, MR 잠금) `local.push_error`에 기록하고
`local.state`를 `replied`로 강등한다. 강등 덕분에 다음 push에서 재시도하지 않는다.

### 5.5 시스템 노트 제거

라벨 변경·할당·approve 등은 `system: true`로 내려온다. `pull` 단계에서 전부 걸러낸다.
안 그러면 노이즈가 절반을 넘는다.

### 5.6 discussion 객체에는 thread 레벨 필드가 없다

GitLab 응답은 `{id, individual_note, notes[]}`뿐이다. `resolved`/`resolvable`/
`updated_at`은 각 note에 있으며 thread 레벨 값은 직접 계산해야 한다. 계산 규칙은
`spec/data-model.md` §4.2에 있다.

### 5.7 개별 노트에는 답글을 달 수 없다

`individual_note: true`인 스레드에 `POST discussions/:id/notes`를 보내면 거부된다.
이것은 "파일 외 코멘트"와 다른 축이다 — diff에 달린 코멘트도 개별 노트일 수 있고,
MR 전체 코멘트도 스레드일 수 있다.

`server.repliable`로 구분해 답글 전송을 생략하고 `no-reply` 배지를 붙인다. 새
discussion을 만드는 우회는 하지 않는다 — 스레드가 아닌 곳에 스레드를 만들면 GitLab
UI에서 맥락이 끊긴다. future work.

### 5.8 파일 외 코멘트

MR 전체에 달린 코멘트는 `position`이 없다. `position: null`로 두고 `review.md` 상단의
`(general)` 섹션에 모은다. 진단으로는 표시하지 않는다.

### 5.9 md 파서는 AI 생성 마크다운을 견뎌야 한다

답글에 표, 수평선, 중첩 코드 펜스, 심지어 앵커 문법의 인용이 평범하게 들어온다.
reply 종결자를 `---`로 두면 바로 깨진다. 종결자는 "다음 앵커 또는 EOF"이고, fenced
code block 안에서는 앵커를 인식하지 않는다. `### reply` 밖은 전부 무시한다.

이 설계 덕분에 "인용을 수정하지 마세요" 같은 지킬 수 없는 규칙이 필요 없어진다
([0004](decisions/0004-single-edit-surface-hardened-grammar.md)).

펜스 추적의 대가는 **답글이 펜스를 닫지 않으면 블록 경계를 확정할 수 없다**는
것이다. 생산에서 모든 텍스트 앵커 스레드가 ` ```diff ` 블록을 렌더하므로, 열린
펜스는 다음 스레드의 그 블록 닫는 줄에서 닫히고 그 사이의 앵커와 헤더가 통째로
삼켜진다 — 사람의 체크가 버려지고 앞 스레드의 답글이 그 마크업을 흡수한다. 그래서
파서는 펜스 때문에 건너뛴 앵커 id를 기록하고, 그 id가 `review.json`에 있으면서
블록이 없을 때 `sync`가 exit 2로 끊는다 (`spec/review-md.md` §7). 인용은 json에
없는 id를 쓰므로 두 경우가 정확히 갈린다.

### 5.10 파일 감시는 `review.json`이 아니라 그 디렉터리에 건다

CLI가 temp 파일 + `os.replace`로 쓰므로 inode가 매번 바뀐다. 파일에 건 watch는 첫
교체 뒤 끊긴 inode에 남아 **조용히 죽고**, 증상은 "코멘트가 있는데 진단이 갱신되지
않는다"뿐이다. 디렉터리에 걸면 첫 `pull`이 json을 만드는 순간도 잡는다.

**테스트는 두 번 연속 고쳐야 이 결함을 본다.** Emacs는 파일 watch도 부모 디렉터리를
보므로 동등하지만 VSCode는 같은 보장을 가정할 수 없다 (`spec/editor.md` §3.1).

### 5.11 소스 버퍼는 "닫히지 않은 것"을 보여준다

flymake는 닫힌 스레드를 감춘다 — 서버가 닫았든(`server.resolved`) 내가
닫았든(`skipped`). 단 미전송 답글(`local.reply`)이 있으면 보인다. `state == todo`로
거르면 `[~]`(답글만)와 미전송 `[x]`가 사라지는데, 전자는 서버에서 살아 있는 대화이고
후자는 아직 보낼 것이 남은 스레드다.

`review.md`는 `skipped`도 보여준다 — 거기는 결정을 **바꾸는** 면이다
(`spec/editor.md` §3.1).

### 5.12 `bulk_publish`는 내 draft 전부를 발행한다

선택적 발행 파라미터가 없으므로 GitLab UI에서 쓰던 미완성 draft까지 함께 공개된다.
mrq가 만들지 않은 draft가 있으면 확인을 요구한다.

draft 생성은 **전송이 아니다** — `pushed_hash`와 `local.reply`는 발행 시점에만
갱신한다 ([0012](decisions/0012-draft-is-not-a-send.md), `spec/cli.md` §9).

### 5.13 응답에서 사라진 스레드

`pull`은 서버 응답에 없는 스레드를 제거하지만, **미전송 작업이 있으면 지우지 않고**
`server.missing`으로 표시하고 `push`가 제외한다. 실제 삭제와 페이지 결손 같은 일시적
결손을 응답만으로 가를 수 없고, 전송하지 않은 답글은 복구 불가능하다
([0011](decisions/0011-preserve-missing-threads.md), `spec/data-model.md` §4.10).

---

## 6. Future work

| 항목 | 메모 |
|---|---|
| 위치 없는 경고를 `review.md` 안에 렌더 | 지금은 메시지 면(에코 영역·`*mrq*`)으로만 보낸다(`editor.md` §3.4). 조용해서 놓치면 "전송되지 않는 답글" 을 모르게 된다. 렌더러·파서가 함께 움직이고 `v:` 해시에 포함할지를 정해야 한다 — `plans/residuals.md` |
| 개별 노트에 답글 | 새 discussion 생성 방식의 UX를 먼저 검토 |
| `suggestions` 적용 (`mrq apply-suggestion`) | 응답 원본을 이미 보관하므로 추가 비용이 작다 |
| Windows 지원 | 심링크, 경로 처리 |
| 스키마 마이그레이션 | v2가 생길 때 |
| 팀 배포 | GitLab 버전별 기능 탐지, `glab` 미설치 폴백 |
| fork / 다중 리모트 | `glab`의 `-R`을 노출하면 된다 |
