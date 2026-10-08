# 0006. 하위 프로젝트 셋을 단일 리포에서 관리한다

날짜: 2026-10-11 · 상태: 채택

## 배경

구현해야 할 하위 프로젝트가 셋이다 — Python CLI, Emacs 플러그인, VSCode 확장. 초안과
스펙 1차 작성에는 이 셋이 어떻게 나뉘고 어떤 도구로 관리되는지에 대한 계획이 없었다.

셋은 하나의 계약을 공유한다: `schema/review.schema.json`, `review.json` 의미, 종료 코드,
그리고 [0003](0003-split-reanchoring-responsibility.md)이 세 언어에 복제한 "저장하지
않은 버퍼의 앵커 한 줄 검색".

## 결정

**단일 리포.** 루트에 하위 프로젝트를 평평하게 둔다.

```
cli/  plugin_emacs/  plugin_vscode/
schema/  testdata/  docs/  Makefile
```

툴체인은 하위별로 다르되(`uv` / `make` + batch ERT / `npm`) 루트 `Makefile`이 단일
진입점을 제공한다.

공유 데이터는 어느 하위도 소유하지 않는 `testdata/`에 둔다. GitLab API 응답 픽스처는
CLI만 쓰므로 `cli/tests/fixtures/`에 남는다.

## 근거

- 스키마나 종료 코드 변경은 세 곳에 **원자적으로** 들어가야 한다. 리포를 나누면
  에디터가 조용히 깨진 상태로 남는다
- 범위가 개인 사용이므로 분리할 외부 요인이 없다. MELPA와 VSCode 마켓플레이스는
  모두 서브디렉터리 발행이 가능하므로 나중에 배포로 가도 구조를 바꾸지 않는다
- `editors/emacs/` 대신 `plugin_emacs/`를 쓰는 이유는 깊이다. `plugin_` 접두사가
  알파벳 정렬로 둘을 붙여놓으므로 그룹화도 유지된다
- `cli/`를 루트에 두면 `pytest`가 cd 없이 돌지만 리포 루트가 Python 프로젝트가 되고
  "하위 프로젝트 셋"이라는 구조가 흐려진다

## 결과

- **적합성 테이블이 필요하다.** [0003](0003-split-reanchoring-responsibility.md)의
  중복 로직이 세 언어에서 같게 동작한다는 보장은 스펙 문장으로는 얻을 수 없다.
  `testdata/conformance/anchor.json`을 세 구현이 모두 읽어 같은 테이블을 돌린다.
  이것이 drift를 막는 유일한 강제 장치다
- 에디터는 CLI 버전이 아니라 `schema_version`을 본다. 따로 업데이트해도 조용히
  깨지지 않는다
- `mrq-mode`는 `markdown-mode`에 하드 의존한다. 조건부 파생은 두 경로를 다 테스트해야
  하고 얻는 것이 범위 A에서는 없다
- Eask와 `@vscode/test-electron`은 도입하지 않는다. 발행과 UI 테스트가 필요해지는
  시점의 선택이다
