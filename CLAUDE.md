# mrq

GitLab MR의 리뷰 코멘트를 로컬 파일로 내려받아 Emacs/VSCode/AI가 함께 다루고,
다시 GitLab에 반영하는 도구.

**작업 전에 `docs/mrq-design.md`를 반드시 읽을 것.** 아래는 요약이며, 충돌 시 설계
문서가 우선이다. 규범적 정의는 `docs/spec/`에 있고, 설계 문서와 충돌하면 스펙이 우선이다.

| 문서 | 내용 |
|---|---|
| `docs/PRD.md` | 목적·성공 기준·시나리오·FR 목록 |
| `docs/mrq-design.md` | 아키텍처와 근거, 함정 |
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
  CLI를 호출한다. 유일한 예외는 저장 안 된 버퍼의 앵커 한 줄 검색이며, 범위는
  `docs/spec/reanchoring.md` §6에 묶여 있다.
- `.mrq/<iid>/review.json`이 정본. `review.md`는 편집면이며 json에서 재생성 가능하다.
- `review.md` 파싱은 줄 위치가 아니라 `<!-- mrq:ID v:HASH -->` 앵커 기준.
- `sync`(md → json + 재앵커링, 네트워크 없음)와 `push`(json → GitLab)는 반드시 분리한다.
- 인증은 직접 구현하지 말고 `glab api` 서브커맨드에 위임한다.
- 사람과 AI는 대등한 경로다. 둘이 동시에 작업하는 것이 정상이다.

## 반드시 지킬 것

함정만 모았다. 구현 전에 해당 스펙을 읽을 것.

- **라인 드리프트** — 위치는 `git diff` hunk 맵으로 구한다. 문자열 탐색은 fallback이고,
  `head_sha`를 로컬에 확보하는 단계가 선행한다. `docs/spec/reanchoring.md`
- **`stale`에는 진단을 띄우지 않는다.** 파일 1행에 붙이지 말 것 — 위치 신뢰를 잃는
  가장 빠른 길이다.
- **discussion 객체에 thread 레벨 `resolved`/`resolvable`/`updated_at`이 없다.**
  notes에서 계산한다. `individual_note: true`인 스레드에는 답글을 달 수 없다.
- **`system: true` 노트는 pull에서 전량 제외한다.** 안 걸러내면 노이즈가 절반을 넘는다.
- **resolve 권한은 `pull`에서 확인해 `status`가 사전에 알린다.** 403을 사후 에러로
  다루지 않는다.
- **`review.json` 이 아니라 그 디렉터리에 파일 감시를 건다.** CLI 가 `os.replace`
  로 쓰므로 inode 가 바뀌고, 원시 inotify 에서는 파일 watch 가 첫 교체 뒤 조용히
  죽는다. Emacs 는 파일 watch 도 부모 디렉터리를 보므로 동등하지만 VSCode 는
  확인이 필요하다. **테스트는 두 번 연속 고쳐야 이 결함을 본다.**
  `docs/spec/editor.md` §3.1
- **flymake 는 "닫힌 스레드" 를 감춘다 — 서버가 닫았든(`server.resolved`) 내가
  닫았든(`skipped`). 단 미전송 답글(`local.reply`)이 있으면 보인다.**
  `state == todo` 로 거르면 `[~]`(답글만)와 `[x]` 미전송이 사라진다.
  `review.md` 는 `skipped` 도 보여준다 — 거기는 결정을 바꾸는 면이다.
  `docs/spec/editor.md` §3.1
- **`push`는 스레드마다 결과를 즉시 json에 쓴다.** 중간에 죽어도 복구 가능해야 한다.
  중복 전송 방지는 `pushed_hash`이고, 전송 성공 시 `local.reply`를 비운다.
  `docs/spec/cli.md` §9
- **`bulk_publish`는 내 draft 전부를 발행한다.** 선택적 발행이 없다. mrq 가 만들지
  않은 draft 가 있으면 확인을 요구한다. draft 생성은 전송이 아니므로 `local.reply`
  를 비우지 않는다. `docs/decisions/0012-draft-is-not-a-send.md`
- **응답에서 사라진 스레드에 미전송 작업이 있으면 지우지 않는다.** `server.missing`
  으로 표시하고 `push` 는 제외한다. `docs/spec/data-model.md` §4.10
- **충돌은 스레드 단위.** 서로 다른 스레드를 고치는 것은 충돌이 아니다. 하나라도
  충돌하면 아무것도 쓰지 않는다. `docs/spec/data-model.md` §5

## 하지 말 것

- `review.md`를 VSCode 확장이나 flymake 백엔드에서 파싱하지 말 것. json을 읽는다.
- 파싱 실패 시 부분 적용하지 말 것. 전부 성공하거나 아무것도 쓰지 않는다.
  단, 에러와 경고를 구분한다 (`docs/spec/review-md.md` §7).
- 리포 루트의 `.gitignore`도 `.git/` 아래도 건드리지 말 것. `.mrq/.gitignore`에 `*`를
  자동으로 쓴다.
- `git remote get-url origin`을 파싱하지 말 것. `glab api`의 `:fullpath`를 쓴다.
- 답글 본문을 CLI 인자로 넘기지 말 것. `-F body=@-`로 stdin을 쓴다.
- 에디터에서 `review.json`을 직접 쓰지 말 것. `mrq reply`/`state`/`sync`를 호출한다.
- 세 구현이 공유하는 테스트 데이터를 `cli/tests/` 안에 두지 말 것. `testdata/`에 둔다.
- 에디터의 앵커 보정 로직을 추가하거나 바꿀 때 `testdata/conformance/anchor.json`을
  갱신하지 않고 넘어가지 말 것. 세 구현이 어긋나는 것을 막는 유일한 장치다.
- flycheck 대신 flymake를 쓴다. VSCode Diagnostics API와 개념이 1:1로 대응된다.

## 명령

루트에서 `make`를 쓴다. 하위마다 다른 도구를 외우지 않는다.

```bash
make test              # 세 하위 전부
make test-cli          # Python만
make test-emacs        # 계획 4 까지는 안내 메시지만
make test-vscode       # 계획 5 까지는 안내 메시지만
make conformance       # 적합성 테이블 교차 실행 (계획 4 에서 생김)
make lint
make deps
```

**`make`는 venv 가 활성화된 셸을 가정한다.** 활성화하지 않았다면 venv 바이너리를
직접 부르는 쪽이 확실하다 — `make`가 `/usr/bin/python` 을 집어 `No module named
pytest` 로 실패한다:

```bash
cd cli && ./.venv/bin/python -m pytest          # 전체
cd cli && ./.venv/bin/python -m pytest -k anchor
cd cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
```

venv 가 없으면 `cd cli && uv sync && uv pip install -e .` (또는 `pip install -e .`).

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
