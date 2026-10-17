# mrq

GitLab MR의 리뷰 코멘트를 로컬 파일로 내려받아 Emacs/VSCode/AI가 함께 다루고,
다시 GitLab에 반영하는 도구.

**작업 전에 `docs/mrq-design.md`를 반드시 읽을 것.** 아래는 요약이며, 충돌 시 설계
문서가 우선이다. 규범적 정의는 `docs/spec/`에 있고, 설계 문서와 충돌하면 스펙이 우선이다.

| 문서 | 내용 |
|---|---|
| `docs/PRD.md` | 목적·성공 기준·시나리오·FR 목록 |
| `docs/mrq-design.md` | 아키텍처와 근거, **함정 전체(§5)** |
| `docs/spec/data-model.md` | `review.json`, 상태 저장 위치, 충돌 감지 |
| `docs/spec/reanchoring.md` | 위치 재계산 — 품질을 좌우하는 부분 |
| `docs/spec/review-md.md` | 편집면 문법과 파싱 |
| `docs/spec/cli.md` | 명령 계약, 종료 코드, `glab` 위임 |
| `docs/spec/editor.md` | 에디터 플러그인의 역할 경계 |
| `docs/spec/testing.md` | 공통 테스트 인프라 |
| `docs/spec/repo-layout.md` | 리포 구조, 하위 프로젝트 툴체인, 적합성 테이블 |
| `docs/decisions/` | 주요 갈림길의 선택과 근거 |
| `docs/plans/README.md` | **계획 1~5 로드맵.** 다음에 무엇을 할지는 여기부터 |
| `docs/plans/` | 진행 중인 계획서와 잔여 항목 |

## 구조

하위 프로젝트 셋을 단일 리포에서 관리한다. 자세한 것은 `docs/spec/repo-layout.md`.

```
cli/            Python CLI       uv, pytest, ruff
plugin_emacs/   elisp            make + batch ERT, 격리된 .elpa
plugin_vscode/  TypeScript       npm, vitest
schema/         세 구현이 공유하는 계약
testdata/       세 구현이 공유하는 테스트 데이터
```

## 핵심 원칙

- 네트워크와 git 접근은 파이썬 CLI(`mrq`)만 담당한다. 에디터 플러그인은 파일을 읽고
  CLI를 호출한다. 유일한 예외는 버퍼 안의 앵커 한 줄 검색이며, 범위는
  `docs/spec/reanchoring.md` §6에 묶여 있다.
- `.mrq/<iid>/review.json`이 정본. `review.md`는 편집면이며 json에서 재생성 가능하다.
  에디터는 md를 파싱하지 않고 json을 읽으며, 상태는 CLI를 통해서만 바꾼다.
- `review.md` 파싱은 줄 위치가 아니라 `<!-- mrq:ID v:HASH -->` 앵커 기준.
- `sync`(md → json + 재앵커링, 네트워크 없음)와 `push`(json → GitLab)는 반드시 분리한다.
- 인증은 직접 구현하지 말고 `glab api` 서브커맨드에 위임한다.
- 사람과 AI는 대등한 경로다. 둘이 동시에 작업하는 것이 정상이다.
- 쓰기는 전부 성공하거나 아무것도 쓰지 않는다. 원자적 교체와 락이 그 수단이다.
- 세 구현이 공유하는 계약(`schema/`, `testdata/`)은 세 곳을 함께 바꾼다. 특히 앵커
  보정을 건드리면 `testdata/conformance/anchor.json`을 같은 커밋에서 갱신한다 —
  세 구현이 어긋나는 것을 막는 유일한 장치다.

## 함정

**함정은 `docs/mrq-design.md` §5에 모여 있다** — 라인 드리프트부터 draft 발행까지,
각 항목이 증상과 규범 스펙의 절을 함께 가리킨다. 구현 전에 그 절을 훑고, 건드릴
영역의 스펙을 읽는다.

규범은 스펙의 MUST / MUST NOT 한 벌이다. 여기에 복사하지 않는다 — 두 벌이 되면
어긋나고, 늘 로드되는 이 파일이 낡으면 그대로 거짓이 된다.

## 명령

루트에서 `make`를 쓴다. 하위마다 다른 도구를 외우지 않는다. (`uv` 도구 필요)

```bash
make test              # 세 하위 전부
make test-cli          # ARGS 인자로 테스트 범위를 좁힐 수 있다: make test-cli ARGS="-k anchor"
make test-emacs        # elisp ERT
make test-vscode       # 계획 5 까지는 안내 메시지만
make conformance       # 적합성 테이블 교차 실행
make lint
make fmt               # ruff format + ruff check --fix
make deps              # 의존을 다시 받고 싶을 때만
```

## 작업 방식

- 한 번에 한 단계씩. 단계가 끝나면 테스트를 돌리고 멈춘다.
  단계 목록, FR·계획 매핑, 계획별 범위는 모두 `docs/plans/README.md`에 있다.
- 계획이 끝나면 그 계획서를 지우고 `docs/plans/README.md`의 표를 갱신한다.
  계획서에만 있던 내용(모듈 분해, 제약)은 지우기 전에 스펙으로 옮긴다.
- 설계가 바뀌면 `docs/mrq-design.md`와 해당 스펙을 같이 갱신한다. 갈림길을 새로
  선택했다면 `docs/decisions/`에 기록을 추가한다.
- API 응답은 `cli/tests/fixtures/`에 픽스처로 저장해 네트워크 없이 테스트한다.
  세 구현이 공유하는 데이터는 `testdata/`에 둔다.
- `glab`과 `git`은 모킹하지 말 것. 가짜 `glab`을 PATH에 꽂고, git은 임시 저장소를
  실제로 만든다 (`docs/spec/testing.md`).
