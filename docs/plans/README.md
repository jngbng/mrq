# 구현 계획 로드맵

구현을 다섯 개의 계획으로 나눠 실행한다. 각 계획은 **그 자체로 동작하는 결과물**을
내고, 끝나면 계획서를 지우고 이 문서를 갱신한다 — 완료된 계획의 내용은 코드와
git 히스토리, 그리고 스펙에 남는다.

| 계획 | 단계 | 결과물 | 상태 |
|---|---|---|---|
| 1 | 0~3 | `mrq pull`이 정확한 `review.json`을 만든다 | **완료** (2026-10-12, 43 커밋) |
| 2 | 4~8 | 렌더 → 편집 → `sync` → `status`. AI가 코멘트를 처리할 수 있다 | **완료** (2026-10-13, 17 커밋) |
| — | — | **계획 3 전 과제** — 잔여 항목 R6·R7·R3·R4 | **완료** (2026-10-13) |
| 3 | 9, 10, 12 | `push`까지 완결된 CLI | **완료** (2026-10-14, 26 커밋) |
| 4 | 11 | `plugin_emacs` | |
| 5 | 13 | `plugin_vscode` | |

새 계획을 시작할 때는 `superpowers:writing-plans`로 `docs/plans/YYYY-MM-DD-<주제>.md`를
쓴다. 실행은 `superpowers:subagent-driven-development`.

## 단계와 FR 매핑

한 번에 한 단계씩. 단계가 끝나면 테스트를 돌리고 멈춘다.

| # | 단계 | FR | 계획 | 상태 |
|---|---|---|---|---|
| 0 | 리포 스캐폴딩 — `Makefile`, `cli/`, `schema/`, `testdata/` | — | 1 | 완료 |
| 1 | 상태 저장 위치, 원자적 쓰기, 락, 스키마 검증 | FR-018 | 1 | 완료 |
| 2 | `mrq pull` — discussions 조회, 시스템 노트 필터, 파생 필드 | FR-001, FR-002 | 1 | 완료 |
| 3 | **재앵커링 + 테스트 12종 + 품질 게이트** | FR-003 | 1 | 완료 |
| 4 | `review.md` 렌더러 | FR-004 | 2 | 완료 |
| 5 | `mrq sync` 파서 + 라운드트립 property 테스트 | FR-005 | 2 | 완료 |
| 6 | 충돌 감지 + `--prefer` | FR-006 | 2 | 완료 |
| 7 | `mrq status`, `mrq list` | FR-007 | 2 | 완료 |
| 8 | `mrq reply`, `mrq state` | FR-012 | 2 | 완료 |
| 9 | `mrq push` (일반 notes 경로) + 멱등성 테스트 | FR-008 ~ FR-011 | 3 | 완료 |
| 10 | `mrq doctor`, `mrq clean`, `mrq open` | FR-016, FR-017, FR-019 | 3 | 완료 |
| 11 | `mrq.el` — flymake 백엔드 먼저, 목록 버퍼 나중 | FR-014 | 4 | |
| 12 | `--draft` 모드 | FR-013 | 3 | 완료 |
| 13 | VSCode 확장 | FR-015 | 5 | |

1번이 가장 앞인 이유: 원자성을 뒤늦게 추가하면 모든 쓰기 경로를 다시 훑어야 하고,
저장 위치를 바꾸면 이미 쌓인 리뷰 상태가 고아가 된다. 남은 계획에도 같은 모양의
항목이 있다 — 계획 3의 `glab.api` 확장이 그렇다.

FR 정의는 `docs/PRD.md` §5, 각 FR의 규범 스펙은 그 표의 마지막 열이 가리킨다.

---

## 계획 1 — 완료

0~3단계. `mrq pull`과 `mrq reanchor`가 동작하고, 재앵커링 품질 게이트가
`exact 17 / fuzzy 3 / stale 1`(81% / 4.8%, 목표 ≥75% / ≤10%)로 통과한다. 163개 테스트.

구현된 FR: FR-001(MR 탐지), FR-002(코멘트 수집), FR-003(재앵커링), FR-018(상태 저장).

**잔여 항목은 `2026-10-12-cli-core-residuals.md`에 있다.** 최종 브랜치 리뷰가
"나중에"로 판정한 것들이고, 각 항목에 그것을 먼저 필요로 하는 계획이 적혀 있다.
계획 2를 시작하기 전에 읽을 것.

---

## 계획 2 — 완료

4~8단계. `pull` → `review.md` 편집 → `sync` → `status`가 한 바퀴 돈다. 사람과 AI가
`review.md`로 코멘트를 처리하거나, `mrq reply`/`mrq state`로 md를 거치지 않고 직접
쓸 수 있다 — 어느 경로로 쓰든 재렌더가 `v:` 해시를 함께 갱신해 거짓 충돌이 생기지
않는다. 전송(`push`)은 아직이다. 304개 테스트.

구현된 FR: FR-004(렌더), FR-005(파싱), FR-006(충돌 감지), FR-007(status·list),
FR-012(reply·state).

**잔여 항목은 `2026-10-12-cli-core-residuals.md`에 있다.** (R1·R2는 이 계획의
첫 두 과제로, R6·R7은 아래 "계획 3 전 과제"로 해소됐다.) 각 항목에 그것을 먼저
필요로 하는 계획이 적혀 있다. 계획 3을 시작하기 전에 읽을 것.

---

## 계획 3 전 과제 — 완료

잔여 항목 중 계획 3을 막는 것들을 계획 3과 분리해 먼저 해소했다
(브랜치 `jbseo/pre_step3` 와 `jbseo/pre_step3_glab`).

| 항목 | 내용 | 상태 |
|---|---|---|
| R6 | 멀티라인 코멘트가 범위의 끝에 앵커를 걸고 span을 잃는다 | 완료 |
| R7 | 노트 시각이 UTC로 렌더된다 | 완료 |
| R3 | `glab.api`가 HTTP 상태를 돌려주지 않는다 (+ 브랜치 이름 쿼리 인코딩) | 완료 |
| R4 | 가짜 `glab`이 페이지네이션·상태 코드·호출별 응답을 표현하지 못한다 | 완료 |

R6·R7은 둘 다 **손으로 쓴 픽스처가 구현과 같은 틀린 가정을 공유해** 테스트를
통과하고 있던 경우였다. 실제 MR 응답과 대조해야만 보이는 종류다
(`spec/testing.md` §3). R3·R4를 할 때도 같은 함정을 가정할 것.

---

## 계획 3 — 완료

9, 10, 12단계. `push`까지 완결된 CLI. 답글과 resolve가 GitLab에 올라가고, 중간에
죽어도 중복 없이 복구된다. `--draft`/`--publish`로 리뷰 한 라운드를 묶어 보낼 수
있다. 483개 테스트.

구현된 FR: FR-008~FR-011(`push`, 일반 notes 경로 + 멱등성), FR-016(`doctor`),
FR-017(`clean`), FR-019(`open`), FR-013(`--draft`).

설계에서 스펙에 반영된 것 셋 — `server.missing`으로 사라진 스레드를 보존하고
`push`가 제외한다(결정 0011), draft 생성은 전송이 아니므로 `local.reply`와
`pushed_hash`를 발행 시점에만 갱신하고 `bulk_publish`는 확인을 요구한다(결정
0012), `status`의 `push` 블록과 `push`의 사전 판정은 같은 함수를 쓴다
(`spec/cli.md` §8).

### 실측 — 읽기 절반만 (2026-10-14)

`gitlab.com/jngbng/mr-helper` MR `!1`(코멘트 15개)을 클론해 `pull` → `status` →
`push --dry-run`을 돌렸다. `pull` 3.2초, 재앵커링 exact 12 / fuzzy 0 / stale 0
(위치가 있는 12건 전부 exact, 나머지 3건은 `location: null`인 개별 노트/일반
코멘트라 재앵커링 통계에서 빠진다), `status` 0.15초, `push --dry-run` 0.7초
("보낼 것이 없습니다" — 모든 스레드가 아직 처리 전 `todo`). 가장 시간을 쓴
지점은 네트워크 왕복(`pull`의 3.2초 대부분)이고, 로컬 계산(`status`/`dry-run`)은
1초 미만이다.

**쓰기 절반(코멘트 처리 + `mrq push`)은 돌리지 않았다.** 아래 체크리스트로
이어서 할 것.

### 남은 측정 — 쓰기 절반 (사용자 판단으로 미룸)

`mrq push`(실제 전송)는 `gitlab.com/jngbng/mr-helper` MR `!1`의 코멘트 15개를
**소비한다** — 답글이 올라가고 스레드가 resolve된다. 다시 쓸 수 없는 픽스처이므로
언제 돌릴지는 작업자가 정한다.

```bash
cd /path/to/mr-helper-clone   # git checkout feat/retry
# review.md 를 AI 와 사람이 처리 — 15개 코멘트에 답글/상태를 채운다
time mrq sync
mrq status
time mrq push --dry-run       # 처리 후 숫자로 다시 확인
time mrq push
```

`spec/testing.md` §8의 표를 그대로 채운다 — 위 읽기 절반의 두 줄은 이미 메웠다:

| 단계 | 측정 | 기록 |
|---|---|---|
| `mrq pull` 실행 시간 | 초 | 3.2초 (2026-10-14 실측) |
| 재앵커링 결과 | exact / fuzzy / stale | exact 12 / fuzzy 0 / stale 0 (2026-10-14 실측) |
| 위치가 틀려서 직접 찾은 코멘트 수 | 건 | |
| 코멘트별 처리 시간 | 초 (유형별) | |
| `mrq status` 확인 시간 | 초 | 0.15초 (처리 전, 2026-10-14 실측) |
| `mrq push` 실행 시간 | 초 | |
| 총 소요 시간 | 분 | |
| 가장 시간을 많이 쓴 지점 | | |

돌린 뒤 행동 가능한 항목이 나오면 `docs/plans/2026-10-12-cli-core-residuals.md`에
새 항목으로 적는다.

---

## 계획 4 — `plugin_emacs` (11단계)

**결과물:** flymake 백엔드와 목록 버퍼. 소스 ↔ 코멘트 왕복이 닫힌다.

FR-014. 스펙은 `spec/editor.md` §1~3.

**이 계획이 만드는 것 둘.** `plugin_emacs/` 디렉터리 자체와,
`testdata/conformance/anchor.json` 적합성 테이블(`spec/repo-layout.md` §4.1).
**이 구현이 그 테이블의 기준이 되고 계획 5가 그것을 통과해야 한다.** 결정 0003이
"저장 안 된 버퍼의 앵커 한 줄 검색"을 세 언어에 복제했고, 그 테이블만이 셋이 같게
동작하는 것을 강제한다(`spec/repo-layout.md` §4.1). 테이블 없이 계획 5를 시작하면
비교할 기준이 없어 "둘 다 그럴듯하게 동작하지만 서로 다르다"를 발견할 방법이 없다.

**잊기 쉬운 것:** `spec/editor.md` §1의 일곱 줄 규범이 에디터가 할 수 있는 일의
경계다. 특히 `review.md`를 파싱하지 않고, `review.json`을 직접 쓰지 않고,
`schema_version`을 확인하고, git·네트워크를 호출하지 않는다. 위치 보정은
`spec/reanchoring.md` §6의 범위(저장 안 된 버퍼의 `location.line ± 200`, 완전 일치
→ strip 일치, **후보가 유일할 때만**)만 수행한다.

`mrq.el`은 `markdown-mode`에 하드 의존한다. Eask는 쓰지 않는다 — MELPA 발행이
future work인 동안은 `make deps`의 `package-install` 한 줄로 충분하다.

---

## 계획 5 — `plugin_vscode` (13단계)

**결과물:** Diagnostics + CodeLens. 문제 패널과 `F8` 이동.

FR-015. 스펙은 `spec/editor.md` §4.

**계획 4의 적합성 테이블을 통과해야 한다.** 그게 이 계획의 가장 중요한 수락 조건이다.

MVP에서 `@vscode/test-electron` 하네스를 쓰지 않는다. 확장이 얇아 로직(json 읽기,
앵커 검색)이 전부 순수 함수이고 vitest로 덮인다. Diagnostics/CodeLens 배선은 수동
확인으로 둔다.

**잊기 쉬운 것:** CodeLens의 `✓ Resolve` / `💬 Reply`는 `mrq state` / `mrq reply`를
호출한다. md를 파싱하지도, json을 직접 쓰지도 않는다. 그 CLI 명령이 계획 2에
포함된 이유가 바로 이 확장이다.

---

## 계획을 넘어선 것

`docs/mrq-design.md` §6의 future work — 개별 노트 답글, `suggestions` 적용,
Windows 지원, 스키마 마이그레이션, 팀 배포, fork 워크플로.
