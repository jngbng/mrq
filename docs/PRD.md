# Product Requirements Document

## 1. 제품 개요

mrq(MR Queue)는 GitLab MR의 리뷰 코멘트를 로컬 텍스트 파일로 내려받아, 에디터와 AI
에이전트가 같은 방식으로 읽고 답글을 작성한 뒤 다시 GitLab에 반영하는 도구다.

코멘트와 연결된 코드를 손쉽게 오가며 답글을 쓰거나 코드를 고칠 수 있고, 작성한 답글은
한 번에 GitLab에 전송한다. 데이터가 텍스트 파일이므로 AI 에이전트도 사람과 동일한
파일을 읽고 쓴다. 사람과 AI 중 어느 쪽도 부차적인 경로가 아니다.

## 2. 성공 기준

| 지표 | 목표 | 측정 |
|---|---|---|
| **처리 속도** | 코멘트 15개짜리 MR을 **30분 내**에 끝낸다 | 실제 MR로 수동 측정 (`docs/spec/testing.md`) |
| 위치 정확도 (선행 지표) | `confidence == exact`가 **75% 이상**, `stale`이 **10% 이하** | 재앵커링 회귀 테스트 |
| 중복 전송 | 0건 | push 멱등성 테스트 |

처리 속도가 제품의 목표이고, 위치 정확도가 그 선행 지표다. 코멘트가 엉뚱한 줄에 붙으면
사용자가 매 코멘트의 위치를 눈으로 검증하게 되고 시간 예산이 무너진다.

30분 = 코멘트당 120초이며, AI가 1차 처리한 결과를 사람이 검토하는 작업 분포를 가정한다.

| 유형 | 개수 | 개당 | 합계 |
|---|---|---|---|
| AI 제안을 읽고 승인 | 10 | 45초 | 450초 |
| 답글 문구 수정 | 3 | 120초 | 360초 |
| AI가 틀려서 코드를 보고 다시 작성 | 2 | 300초 | 600초 |
| | | 소계 | 1410초 |

여유 390초가 `pull`/`push` 오버헤드와 예상 못 한 코멘트를 흡수한다.

## 3. MVP 범위

### 포함

- 현재 브랜치에 연결된 MR 자동 탐지
- MR 코멘트 수집과 로컬 저장, 작업 트리 기준 위치 재계산
- 코멘트별 처리 상태와 답글 기록, 일괄 전송
- 에디터에서 코멘트 목록 조회와 소스 위치 왕복
- 소스 버퍼에 코멘트를 진단으로 표시
- 사람과 AI가 같은 파일을 공유. AI는 CLI로도 상태를 바꿀 수 있다
- Emacs와 VSCode 지원

### 제외

| 항목 | 이유 |
|---|---|
| GitLab 인증·API 직접 구현 | `glab`에 위임. 사용자가 미리 `glab auth login`을 해둔다 |
| Windows 지원 | 범위 A(개인/리눅스/단일 인스턴스) |
| 스키마 마이그레이션 구현 | 거부 경로만 구현. 마이그레이션은 v2가 생길 때 |
| GitLab 버전별 기능 분기 | `draft_notes` 가용성 탐지만 |
| 개별 노트(`individual_note`)에 답글 전송 | future work. 경고만 표시 |
| 코드 제안(`suggestions`) 적용 | future work. 원본은 보관 |
| 다중 리모트·fork 워크플로 | `origin` 고정 |

## 4. 사용자 시나리오

### 시나리오 1 — 코멘트를 읽어온다

브랜치 `feat/retry`에서 작업 중이다. `mrq pull`을 실행하면 mrq가 소스 브랜치로 MR
`!1234`를 찾고, 코멘트 15개를 받아 시스템 노트를 걸러내고, 각 코멘트의 위치를 **현재
작업 트리 기준으로 다시 계산한다.** `.mrq/1234/review.json`과 `review.md`가 만들어지고
한 줄 요약이 출력된다.

```
!1234 Add retry logic to API client · threads 15 · unresolved 11
reanchored: exact 12 · fuzzy 2 · stale 1   (head abc1234)
```

MR의 head_sha는 로컬에 없을 수 있으므로 필요하면 자동으로 fetch한다.

### 시나리오 2 — 코멘트와 소스를 오가며 맥락을 파악한다

`review.md`를 열면 코멘트가 파일·줄 순서로 정렬되어 있고, 각 코멘트에는 **리뷰어가 본
diff hunk**가 함께 들어 있다. 현재 코드만 보면 코드가 이미 바뀐 뒤라 왜 그런 지적을
했는지 알 수 없기 때문이다.

`M-g n`으로 다음 코멘트로 이동하고 `RET`로 소스로 점프한다. 반대로 소스 버퍼에서는
flymake 진단으로 코멘트가 보이고, `C-c m r`로 해당 코멘트의 답글 작성 위치로 간다.
위치를 신뢰할 수 없는 코멘트에는 `fuzzy`/`stale` 배지가 붙어 있어 어느 것을 눈으로
확인해야 하는지 바로 안다.

### 시나리오 3 — 수정하고 답글과 함께 일괄 반영한다

AI 에이전트에게 `.mrq/current/review.md`를 처리하라고 지시한다. 에이전트는 코멘트를
읽고 코드를 고치고, 체크박스를 `[x]`로 바꾸고 답글을 쓴다. 동의하지 않으면 `[~]`로 두고
이유를 쓴다. 그 사이 사용자는 다른 코멘트를 직접 처리한다. 둘이 같은 코멘트를 서로 다르게
고친 경우에만 충돌로 보고된다.

`mrq status`로 전송될 내용을 확인한다.

```
push      replies 9 · resolves 8 · skip 2
          ⚠ f6e5d4c3 서버에서 변경됨 (pull 이후) — 건너뜀
          ⚠ 7766ccdd 개별 노트라 답글 전송 불가
```

`mrq push`가 답글을 올리고 `[x]`인 스레드를 resolve한다. 중간에 실패해도 재실행하면
중복 없이 이어서 진행한다.

## 5. 핵심 기능 목록

규범적 정의는 각 스펙 문서에 있다. 여기서는 ID와 한 줄 정의, 수락 기준만 둔다.

| ID | 기능 | 수락 기준 | 스펙 |
|---|---|---|---|
| FR-001 | MR 자동 탐지 | 소스 브랜치로 1건이면 채택, 0건·2건 이상은 exit 6 | `spec/cli.md` |
| FR-002 | 코멘트 수집 | `system: true` 전량 제외, 페이지네이션 처리, 서버 파생 필드 계산 | `spec/data-model.md` |
| FR-003 | 재앵커링 | 시나리오 12종 통과, `exact ≥ 75%` / `stale ≤ 10%` | `spec/reanchoring.md` |
| FR-004 | `review.md` 렌더 | 안정 정렬, `v:` 해시 포함, 배지 표시 | `spec/review-md.md` |
| FR-005 | `review.md` 파싱 | 에러 시 아무것도 쓰지 않음, 라운드트립 바이트 일치 | `spec/review-md.md` |
| FR-006 | 충돌 감지 | 스레드 단위 판정, 거짓 충돌 없음, 하나라도 충돌하면 전체 거부 | `spec/data-model.md` |
| FR-007 | 상태 조회 | 전송 예정 내용을 push 전에 보여줌, `--json` 계약 준수 | `spec/cli.md` |
| FR-008 | 전송 | 스레드별 즉시 기록, 중간 종료 후 재실행 가능 | `spec/cli.md` |
| FR-009 | 중복 전송 방지 | `pushed_hash` + 서버 스냅샷 2차 방어 | `spec/cli.md` |
| FR-010 | 동시 변경 감지 | `updated_at`/`note_count` 변경 시 건너뜀, `--force`로 무시 | `spec/cli.md` |
| FR-011 | resolve 권한 처리 | 권한을 pull 시 확인해 사전 표시, 403은 exit 4 + `retryable: false` | `spec/cli.md` |
| FR-012 | CLI 상태 변경 | `reply`/`state`가 json과 md를 함께 갱신 | `spec/cli.md` |
| FR-013 | draft 모드 | 가용성 탐지 후 미지원이면 명시적 거부 | `spec/cli.md` |
| FR-014 | Emacs 통합 | flymake 백엔드, `next-error`, 저장 시 `sync` | `spec/editor.md` |
| FR-015 | VSCode 통합 | Diagnostics + CodeLens, md 파싱 금지 | `spec/editor.md` |
| FR-016 | 환경 진단 | `doctor`가 실패 지점을 특정 | `spec/cli.md` |
| FR-017 | 정리 | merged/closed MR 디렉터리 제거 | `spec/cli.md` |
| FR-018 | 상태 저장 레이아웃 | `.mrq/`, 원자적 쓰기, 락, `.git/info/exclude` 자동 등록 | `spec/data-model.md` |
| FR-019 | 브라우저 열기 | MR 또는 특정 스레드 앵커로 이동 | `spec/cli.md` |

## 6. 비기능 요구사항

| 항목 | 요구 |
|---|---|
| 네트워크 경계 | 네트워크 호출은 `mrq` CLI만. 에디터 플러그인은 파일만 읽고 CLI만 호출한다 |
| 원자성 | 모든 json 쓰기는 temp + `os.replace`. 파싱 실패 시 부분 적용 금지 |
| 동시성 | `.mrq/<iid>/lock`으로 쓰기 직렬화. 에디터의 `sync`와 터미널의 `push`가 겹칠 수 있다 |
| 멱등성 | `push`를 두 번 실행해도 답글이 중복되지 않는다 |
| 복구 가능성 | 어느 시점에 죽어도 재실행으로 복구된다. `review.md`는 json에서 재생성 가능 |
| 출력 계약 | `--json`일 때 stdout은 순수 JSON 하나. 경고·로그·에러는 stderr |
| 성능 | 코멘트 50개 MR에서 `pull` 10초 이내, `sync` 1초 이내 |
| 관측성 | `pull`/`sync`가 재앵커링 품질을 한 줄로 출력한다 |

## 7. 기술 스택

| 영역 | 선택 | 근거 |
|---|---|---|
| 리포 | 단일 리포. `cli/` + `plugin_emacs/` + `plugin_vscode/` | 세 구현이 하나의 계약을 공유한다. 스키마 변경이 원자적이어야 한다 |
| CLI | Python 3.11+, uv (`pip`로도 설치 가능) | 에디터 양쪽에서 호출하기 쉽고 텍스트 처리에 적합 |
| GitLab 접근 | `glab api` 서브프로세스 | 인증·호스트 설정·토큰 저장소를 통째로 위임. self-hosted 설정을 직접 다루지 않는다 |
| git 접근 | `git` 서브프로세스 (plumbing) | 재앵커링의 핵심이 `git diff` 출력이다. 라이브러리로 추상화하면 hunk를 직접 못 본다 |
| 테스트 | pytest + hypothesis (CLI), ERT (Emacs), vitest (VSCode) | 라운드트립을 property로 검증. 중복 로직은 공유 적합성 테이블로 교차 검증 |
| 공통 진입점 | `make` | 하위마다 다른 도구를 외우지 않는다 |
| 포맷·린트 | ruff | |
| Emacs | flymake + `markdown-mode` 파생 모드 | VSCode Diagnostics API와 개념이 1:1 대응. flycheck는 쓰지 않는다 |
| VSCode | Diagnostics + CodeLens | Comments API는 1차 구현에서 과하다 |
| 스키마 검증 | JSON Schema (`schema/review.schema.json`) | 세 구현이 공유하는 계약을 기계로 강제 |
