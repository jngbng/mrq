# 스펙: 리포 구조와 하위 프로젝트

규범 문서. 관련: FR-018, 그리고 세 구현 전체

하위 프로젝트가 셋이다 — Python CLI, Emacs 플러그인, VSCode 확장. 셋은 하나의 계약을
공유한다(`schema/review.schema.json`, `review.json` 의미, 종료 코드, 그리고
[0003](../decisions/0003-split-reanchoring-responsibility.md)이 만든 앵커 검색 중복
로직). 이 문서는 그 셋이 어떻게 나뉘고, 무엇이 계약 drift를 막는지 정한다.

---

## 1. 단일 리포

세 하위 프로젝트를 한 리포에서 관리한다(MUST).

스키마나 종료 코드가 바뀌면 세 곳이 **동시에** 바뀌어야 한다. 리포를 나누면 그 변경이
원자적이지 않고, 에디터가 조용히 깨진 상태로 남는다. 범위가 개인 사용이라 분리할
이유도 없다.

MELPA와 VSCode 마켓플레이스는 둘 다 서브디렉터리에서 발행할 수 있으므로 나중에
배포로 넘어가도 구조를 바꿀 필요가 없다.

---

## 2. 레이아웃

```
mrq/
  Makefile                       세 하위의 공통 진입점
  README.md  CLAUDE.md
  docs/
    PRD.md  mrq-design.md
    spec/  decisions/
  schema/
    review.schema.json           세 구현이 공유하는 계약
  testdata/                      어느 하위도 소유하지 않는 공유 데이터
    review/*.json                  완성된 review.json 샘플
    conformance/anchor.json        앵커 검색 적합성 테이블
  cli/
    pyproject.toml
    src/mrq/
    tests/
      fixtures/                    glab API 응답 (CLI 전용)
      bin/glab                     가짜 glab
  plugin_emacs/
    mrq.el  mrq-flymake.el  ...
    test/
  plugin_vscode/
    package.json  tsconfig.json
    src/  src/test/
```

### `testdata/`를 분리하는 이유

픽스처에는 두 종류가 있고 소유자가 다르다.

| 디렉터리 | 내용 | 읽는 주체 |
|---|---|---|
| `cli/tests/fixtures/` | GitLab API 응답 | CLI만 |
| `testdata/review/` | 완성된 `review.json` 샘플 | **세 구현 전부** |
| `testdata/conformance/` | 적합성 테이블 | **세 구현 전부** |

후자를 `cli/tests/` 안에 두면 elisp 테스트가 `../../cli/tests/fixtures/`를 참조하게
되고, 에디터 테스트가 Python 테스트 디렉터리 구조에 묶인다. 공유 데이터는 공유
위치에 둔다(MUST).

### `cli/`를 루트에 두지 않는 이유

CLI를 루트에 두면 `pytest`가 cd 없이 돌아 편하지만 리포 루트가 Python 프로젝트가
되고 "하위 프로젝트 셋"이라는 구조가 흐려진다. `make test-cli`로 해결되는 비용이다.

---

## 3. 툴체인

| 하위 | 매니저 | 테스트 | 린트 |
|---|---|---|---|
| `cli` | uv (PEP 621 `pyproject.toml`) | pytest + hypothesis | ruff |
| `plugin_emacs` | 없음. Makefile + `emacs -Q -batch` | ERT | byte-compile 경고, `checkdoc` |
| `plugin_vscode` | npm + TypeScript | vitest | eslint |

- `cli`는 `pip install -e cli/`로도 설치 가능해야 한다(MUST). uv는 개발 편의이며
  필수 의존이 아니다
- `plugin_emacs`에 Eask를 쓰지 않는다. Eask가 실질적으로 해주는 일은 테스트용
  `markdown-mode` 설치인데, MELPA 발행이 future work인 동안은 `make deps`가
  `package-install`을 돌리는 것으로 충분하다. 발행 시점에 도입한다
- `plugin_vscode`는 MVP에서 `@vscode/test-electron` 하네스를 쓰지 않는다(SHOULD NOT).
  확장이 얇아 로직(json 읽기, 앵커 검색)이 전부 순수 함수이고 vitest로 덮인다.
  Diagnostics/CodeLens 배선은 수동 확인으로 둔다

### `markdown-mode` 하드 의존

`mrq-mode`는 `markdown-mode`에서 파생한다(MUST). 조건부 파생(없으면 `text-mode`)을
하지 않는다(MUST NOT) — 두 경로를 다 테스트해야 하고, 얻는 것은 `markdown-mode`가
없는 사용자뿐이다.

`markdown-mode`를 요구하지 않는 코드(flymake 백엔드, 앵커 검색)는 별도 파일에 두어
의존성 없이 테스트할 수 있어야 한다(SHOULD).

---

## 4. 계약 drift를 막는 장치

[0003](../decisions/0003-split-reanchoring-responsibility.md)이 "저장하지 않은 버퍼의
앵커 한 줄 검색"을 세 언어에 복제했다. `docs/spec/reanchoring.md` §6가 범위를 규범으로
묶었지만, 문장만으로는 셋이 같게 동작한다는 보장이 없다.

### 4.1 적합성 테이블

`testdata/conformance/anchor.json`을 **세 구현이 모두 읽어 같은 테이블을 돌린다**(MUST).

```jsonc
[
  { "name": "유일한 후보를 채택한다",
    "buffer": ["def f():", "    x = 1", "    y = 2"],
    "anchor_line": "    x = 1",
    "location_line": 1,
    "expect": 2 },

  { "name": "후보가 둘이면 보정하지 않는다",
    "buffer": ["    x = 1", "", "    x = 1"],
    "anchor_line": "    x = 1",
    "location_line": 1,
    "expect": 1 },

  { "name": "완전 일치가 없으면 strip 일치를 쓴다",
    "buffer": ["def f():", "        x = 1"],
    "anchor_line": "    x = 1",
    "location_line": 1,
    "expect": 2 },

  { "name": "창(±200) 밖은 보지 않는다",
    "buffer_repeat": { "line": "pass", "count": 500 },
    "buffer_insert": { "at": 400, "line": "    x = 1" },
    "anchor_line": "    x = 1",
    "location_line": 1,
    "expect": 1 }
]
```

| 필드 | 의미 |
|---|---|
| `buffer` | 버퍼 내용. 1-indexed 줄 배열 |
| `buffer_repeat` / `buffer_insert` | 큰 버퍼를 json에 펼치지 않고 생성한다. `buffer`와 배타적 |
| `anchor_line` | `anchor.line` 값 |
| `location_line` | `location.line` 값 (검색 시작점) |
| `expect` | 보정 결과로 기대하는 줄 번호. 보정하지 않으면 `location_line`과 같다 |

하나가 어긋나면 그 구현의 테스트가 깨진다. 스펙 문장보다 강한 강제이며, 유일하게
중복된 로직에 정확히 걸린다.

### 4.2 스키마 교차 검증

세 구현 모두 `testdata/review/*.json`을 `schema/review.schema.json`으로 검증해야
한다(MUST). Python은 `jsonschema`, TypeScript는 `ajv`, Emacs는 최소한 필수 필드와
`enum` 값을 확인한다.

---

## 5. 버전과 결합

- CLI의 버전은 `cli/pyproject.toml` 하나다
- **에디터는 CLI 버전이 아니라 `review.json`의 `schema_version`을 본다**(MUST).
  모르는 버전이면 명확한 메시지와 함께 동작을 거부한다. 에디터와 CLI를 따로
  업데이트해도 조용히 깨지지 않는다
- 에디터가 CLI를 찾는 방법:

| 하위 | 설정 | 기본값 |
|---|---|---|
| `plugin_emacs` | `mrq-executable` (defcustom) | `"mrq"` |
| `plugin_vscode` | `mrq.executablePath` (설정) | `"mrq"` |

PATH 가정이 기본이고 덮어쓸 수 있다. 릴리스 프로세스는 future work.

---

## 6. `make` 진입점

```
make test          세 하위 전부
make test-cli
make test-emacs
make test-vscode
make conformance   적합성 테이블만 (세 구현 교차)
make lint
make deps          emacs: markdown-mode 설치 / vscode: npm ci
```

루트에서 한 명령으로 전부 돌 수 있어야 한다(MUST). 하위마다 다른 도구를 외우게 하지
않는다.
