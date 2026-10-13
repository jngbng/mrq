# `glab.api` 상태 코드와 가짜 `glab` 하네스 (R3 · R4) — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `glab.api()`가 HTTP 상태를 예외에 실어 나르고, 가짜 `glab`이 상태 코드·호출별 응답·다중 페이지를 표현할 수 있게 해 계획 3의 `push`를 TDD로 쓸 수 있게 만든다.

**Architecture:** `api()`는 `paginate=False`일 때 `-i`를 붙여 응답 첫 줄에서 상태 코드를 읽고, 실패를 `GlabError(NetworkError)`로 던진다. `NetworkError`를 상속하므로 종료 코드 5 계약과 기존 호출처가 바뀌지 않는다. 가짜 `glab`의 `routes.json`은 라우트마다 **응답 목록**을 갖고, 진짜 glab이 내는 바이트 모양을 그대로 흉내 낸다.

**Tech Stack:** Python 3.11+, pytest, ruff. 서브프로세스 모킹 없음 — 가짜 `glab`을 PATH에 꽂는다.

**Spec:** `docs/plans/2026-10-13-glab-api-and-harness-design.md`

## Global Constraints

- 브랜치: `jbseo/pre_step3`. 이미 R6·R7이 올라가 있다.
- 테스트: `cd cli && ./.venv/bin/python -m pytest` (시작 시점 **346개 통과**).
- 린트: `cd cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .`
- `make`는 venv가 활성화된 셸을 가정한다. venv 바이너리를 직접 부른다.
- **`glab`과 `git`을 모킹하지 않는다**(MUST NOT). 가짜 `glab`을 PATH에 꽂고, git은 임시 저장소를 실제로 만든다 (`docs/spec/testing.md` §2).
- **가짜 `glab`은 "우리 파서가 읽기 쉬운 것"이 아니라 "진짜 glab이 내는 것"을 내야 한다**(MUST). 실측 바이트 모양: 상태줄은 `\n`으로, 헤더는 `\r\n`으로 끝나고 본문 구분자는 `\r\n\r\n`이다.
- `GlabError.reason`의 열거값은 `forbidden | not-found | conflict | network | unknown` 다섯뿐이다 (`docs/spec/data-model.md` §4.8).
- 등록되지 않은 라우트에서 요란하게 실패하는 하네스 동작을 유지한다(MUST) — 조용히 통과시키면 테스트가 거짓으로 녹색이 된다.
- 각 과제는 **전체 스위트가 녹색인 상태로 끝난다.** 과제 끝의 기대 개수가 맞지 않으면 테스트를 잃은 것이니 멈추고 원인을 찾는다.
- 커밋 메시지는 한국어. 끝에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

## Review Focus

설계가 함축하지만 어느 과제도 직접 건드리지 않는 입력들. 각 줄의 테스트를 해당 과제에 넣었다.

1. **본문이 `\r\n\r\n`을 담은 응답** — 코드 블록이 든 답글이 JSON으로 돌아올 때. **첫** 구분자에서만 잘라야 하고 그 뒤는 전부 본문이다. → Task 2.
2. **상태줄은 있는데 본문이 없는 응답(204)** — `bulk_publish`가 이 모양일 수 있다. 예외가 아니라 `None`이어야 한다. → Task 2.
3. **비2xx인데 stdout이 JSON이 아닌 경우** — 리버스 프록시의 HTML 에러 페이지. 메시지를 만들다 `json.loads`가 터지면 안 된다. → Task 2.
4. **응답 목록이 소진된 뒤의 호출** — 크래시 복구 테스트가 같은 명령을 재실행하므로 반드시 걸린다. 마지막 응답이 반복되어야 한다. → Task 1.
5. **`query` 값에 `=`가 들어가거나 빈 문자열인 경우** — glab은 첫 `=`에서만 쪼갠다. 깨지지 않는 것을 고정한다. → Task 3.

---

## Task 1: 하네스 `routes.json`을 응답 목록으로

동작 변경 없는 정규화. **기존 테스트 346개가 한 줄도 수정되지 않고 통과해야 한다** — 수정이 필요하면 정규화가 잘못된 것이다.

**Files:**
- Modify: `cli/tests/bin/glab`
- Modify: `cli/tests/conftest.py` (`Harness`)
- Test: `cli/tests/test_glab.py`

**Interfaces:**
- Consumes: 없음
- Produces: `Harness.route(key, payload=None, *, raw=None, status=200, pages=None)` — 단일 응답 등록, 기존 호출 모양과 호환
- Produces: `Harness.route_seq(key, responses: list[dict])` — 호출 순서대로 소비될 응답 목록. 각 항목은 `{"payload"|"raw"|"pages", "status"}` 키를 갖는 dict
- Produces: `routes.json` 형식 — `{"<METHOD> <path>": [{"status": int, "file"|"body"|"pages": ...}, ...]}`

- [ ] **Step 1: 실패 테스트를 쓴다**

`cli/tests/test_glab.py` 끝에 추가:

```python
def test_route_seq_returns_a_different_response_per_call(glab):
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    assert glab_mod.api("user") == {"id": 1}
    assert glab_mod.api("user") == {"id": 2}


def test_route_seq_repeats_the_last_response_when_exhausted(glab):
    # 크래시 복구 테스트가 같은 명령을 재실행한다. 목록이 소진되면 마지막
    # 응답이 반복되어야 한다 — 소진을 에러로 만들면 재실행이 하네스 때문에
    # 실패한다.
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    glab_mod.api("user")
    glab_mod.api("user")
    assert glab_mod.api("user") == {"id": 2}
    assert glab_mod.api("user") == {"id": 2}


def test_route_seq_counts_calls_per_route_not_globally(glab):
    # 다른 경로의 호출이 끼어들어도 순서가 밀리면 안 된다. pull 은 한 번에
    # 대여섯 경로를 부른다.
    glab.route_seq("GET user", [{"payload": {"id": 1}}, {"payload": {"id": 2}}])
    glab.route("GET other", {"ok": True})
    assert glab_mod.api("user") == {"id": 1}
    glab_mod.api("other")
    assert glab_mod.api("user") == {"id": 2}
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd cli && ./.venv/bin/python -m pytest tests/test_glab.py -k route_seq -v
```

Expected: FAIL with `AttributeError: 'Harness' object has no attribute 'route_seq'`

- [ ] **Step 3: `Harness`를 고친다**

`cli/tests/conftest.py`의 `Harness` 클래스 **전체**를 아래로 교체한다 (`glab` 픽스처 안의 중첩 클래스이므로 들여쓰기 8칸 기준).

```python
    class Harness:
        def __init__(self) -> None:
            self.routes: dict[str, list[dict]] = {}
            self._files = 0

        def _store(self, text: str) -> str:
            # 파일 이름을 전역 카운터로 뽑는다. len(self.routes) 를 쓰면 같은
            # 키를 다시 등록할 때 이전 파일을 덮어쓴다.
            name = f"r{self._files}.json"
            self._files += 1
            (fixtures / name).write_text(text, encoding="utf-8")
            return name

        def _response(self, payload, raw, status, pages) -> dict:
            response: dict = {"status": status}
            if pages is not None:
                response["pages"] = [self._store(text) for text in pages]
            elif raw is not None:
                response["file"] = self._store(raw)
            elif payload is not None:
                # `[]` 와 `{}` 도 유효한 응답이다. 참/거짓으로 보면 안 된다.
                response["file"] = self._store(json.dumps(payload, ensure_ascii=False))
            else:
                response["body"] = ""
            return response

        def _flush(self) -> None:
            (fixtures / "routes.json").write_text(
                json.dumps(self.routes, ensure_ascii=False), encoding="utf-8"
            )

        def route(
            self,
            key: str,
            payload=None,
            *,
            raw: str | None = None,
            status: int = 200,
            pages: list[str] | None = None,
        ) -> None:
            """`"GET projects/:fullpath/user"` 같은 키에 응답 하나를 등록한다."""
            self.routes[key] = [self._response(payload, raw, status, pages)]
            self._flush()

        def route_seq(self, key: str, responses: list[dict]) -> None:
            """호출 순서대로 소비될 응답 목록. 소진되면 마지막 것이 반복된다."""
            self.routes[key] = [
                self._response(
                    item.get("payload"),
                    item.get("raw"),
                    item.get("status", 200),
                    item.get("pages"),
                )
                for item in responses
            ]
            self._flush()

        def fail_at(self, *indices: int) -> None:
            monkeypatch.setenv("MRQ_GLAB_FAIL_AT", ",".join(str(i) for i in indices))

        def calls(self) -> list[dict]:
            if not log.exists():
                return []
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]
```

- [ ] **Step 4: 가짜 `glab`이 목록을 읽게 한다**

`cli/tests/bin/glab`을 아래 내용으로 **전체 교체**한다.

```python
#!/usr/bin/env python3
"""테스트용 가짜 glab. docs/spec/testing.md §2.

환경변수:
  MRQ_GLAB_FIXTURES  routes.json 과 응답 파일이 있는 디렉터리
  MRQ_GLAB_LOG       호출 기록 (JSON Lines: {"argv": [...], "stdin": "..."})
  MRQ_GLAB_FAIL_AT   N 번째 호출에서 exit 1 (1-indexed, 콤마 구분)

`routes.json` 은 `"<METHOD> <path>"` 마다 **응답 목록** 을 담는다. 그 키로 들어온
호출의 순서대로 소비하고, 목록이 소진되면 마지막 것이 반복된다. 응답 하나는
`{"status": 200, "file"|"body"|"pages": ...}` 다.

`MRQ_GLAB_FAIL_AT` 으로 죽인 호출도 소비한 것으로 센다 — 로그에 남은 호출이
기준이다. "요청은 갔는데 그 뒤에 죽었다" 가 크래시 복구가 다루는 모양이다.

등록되지 않은 경로는 exit 1 이다. 조용히 통과시키면 테스트가 거짓으로 녹색이 된다.
"""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


def route_key(argv: list[str]) -> str:
    method = "GET"
    if "--method" in argv:
        method = argv[argv.index("--method") + 1]
    return f"{method} {argv[1]}"


def _is_api_call(argv: list[str]) -> bool:
    return argv[:1] == ["api"] and len(argv) >= 2


def _body(fixtures: Path, response: dict) -> str:
    if "file" in response:
        return (fixtures / response["file"]).read_text(encoding="utf-8")
    return response.get("body", "")


def main() -> int:
    argv = sys.argv[1:]

    # `-F key=@-` 가 있을 때만 stdin 을 읽는다. 무조건 읽으면 상속된 stdin 에서 막힌다.
    stdin = sys.stdin.read() if any(arg.endswith("=@-") for arg in argv) else ""

    entries: list[dict] = []
    log = os.environ.get("MRQ_GLAB_LOG")
    if log:
        log_path = Path(log)
        if log_path.exists():
            entries = [
                json.loads(line)
                for line in log_path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
        with log_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"argv": argv, "stdin": stdin}, ensure_ascii=False) + "\n")

    fail_at = {
        int(token)
        for token in os.environ.get("MRQ_GLAB_FAIL_AT", "").split(",")
        if token.strip()
    }
    index = len(entries) + 1
    if index in fail_at:
        print(f"fake glab: 호출 {index} 에서 의도적으로 실패", file=sys.stderr)
        return 1

    if not _is_api_call(argv):
        print(f"fake glab: 지원하지 않는 호출 {argv}", file=sys.stderr)
        return 1

    key = route_key(argv)

    fixtures = Path(os.environ["MRQ_GLAB_FIXTURES"])
    routes_path = fixtures / "routes.json"
    routes = json.loads(routes_path.read_text(encoding="utf-8")) if routes_path.exists() else {}
    if key not in routes:
        registered = "\n  ".join(sorted(routes)) or "(없음)"
        print(
            f"fake glab: 등록되지 않은 경로 — {key}\n등록된 경로:\n  {registered}",
            file=sys.stderr,
        )
        return 1

    # 같은 키로 들어온 이전 호출 수가 목록의 인덱스다. 경로별로 센다 —
    # 전체 호출 수로 세면 다른 경로의 호출이 순서를 민다.
    responses = routes[key]
    seen = sum(
        1 for entry in entries if _is_api_call(entry["argv"]) and route_key(entry["argv"]) == key
    )
    response = responses[min(seen, len(responses) - 1)]

    sys.stdout.write(_body(fixtures, response))
    return 0


if __name__ == "__main__":
    sys.exit(main())
```

- [ ] **Step 5: 새 테스트와 기존 테스트가 모두 통과하는지 본다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
```

Expected: **349 passed** (346 + 3)

기존 테스트 파일은 한 줄도 수정하지 않았어야 한다:

```bash
cd /home/bongya/workspace/mrq && git diff --stat cli/tests/
```

Expected: `conftest.py`, `bin/glab`, `test_glab.py` 세 개만. 다른 파일이 나오면 멈추고 원인을 찾는다.

- [ ] **Step 6: 린트하고 커밋한다**

```bash
cd /home/bongya/workspace/mrq/cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd /home/bongya/workspace/mrq && git add -A && git commit -F - <<'EOF'
R4: 가짜 glab 의 라우트를 응답 목록으로

호출별로 다른 응답을 돌려줄 수 있어야 push 멱등성·크래시 복구 테스트를
쓸 수 있다 (testing.md §6). 라우트 값이 목록이 되고 같은 키로 들어온
호출 순서대로 소비한다. 경로별로 세므로 다른 경로의 호출이 순서를 밀지
않는다. 소진되면 마지막 것이 반복된다 — 재실행하는 크래시 복구 테스트가
하네스 때문에 실패하면 안 된다.

기존 route() 호출 모양을 그대로 받으므로 다른 테스트는 수정하지 않았다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 2: 상태 코드를 예외로 나른다

하네스·클라이언트·유일한 `check=False` 호출처가 **한 과제에서** 바뀐다. 하네스가 헤더를 내지 않으면 `api()`의 상태 파싱을 `api()`를 통해 테스트할 수 없고, `check=`를 지우면 `draft_notes_available`이 즉시 깨지므로 같이 고쳐야 스위트가 녹색으로 끝난다.

**Files:**
- Modify: `cli/src/mrq/errors.py`
- Modify: `cli/src/mrq/glab.py`
- Modify: `cli/src/mrq/mr.py` (임포트, `draft_notes_available`)
- Modify: `cli/tests/bin/glab`
- Modify: `cli/tests/test_glab.py`
- Test: `cli/tests/test_glab.py`, `cli/tests/test_mr.py`

**Interfaces:**
- Consumes: Task 1의 `Harness.route(key, payload, status=...)`, `routes.json`의 `{"status": int, ...}`
- Produces: `mrq.errors.GlabError(message, *, status: int | None = None)` — 속성 `status: int | None`, `reason: str`, `retryable: bool`. `NetworkError` 상속이므로 `exit_code == 5`
- Produces: `glab.api(path, *, method, fields, body, paginate)` — `check` 인자 없음. `paginate=False`면 argv에 `-i`

- [ ] **Step 1: 실패 테스트를 쓴다**

`cli/tests/test_glab.py`의 임포트를 바꾼다:

```python
from mrq.errors import GlabError, NetworkError
```

끝에 추가:

```python
def test_include_flag_is_added_when_not_paginating(glab):
    glab.route("GET user", {"id": 7})
    glab_mod.api("user")
    assert "-i" in glab.calls()[0]["argv"]


def test_include_flag_is_not_added_when_paginating(glab):
    # -i 와 --paginate 를 같이 쓰면 glab 이 페이지마다 헤더 블록을 내 ndjson
    # 파싱이 깨진다 (1.114 실측). 그 경로는 상태 코드를 쓰지 않는다.
    glab.route("GET discussions", raw='{"id": "a"}\n')
    glab_mod.api("discussions", paginate=True)
    assert "-i" not in glab.calls()[0]["argv"]


def test_success_strips_headers_and_parses_body(glab):
    glab.route("GET user", {"id": 7, "username": "bongya"})
    assert glab_mod.api("user") == {"id": 7, "username": "bongya"}


def test_body_containing_a_blank_crlf_line_is_not_truncated(glab):
    # 본문 안에 CRLFCRLF 가 들어 있어도 헤더/본문 구분은 **첫** 구분자에서만
    # 일어나야 한다. raw 로 넣는다 — json.dumps 는 CR 을 이스케이프해서
    # 실제 바이트가 들어가지 않는다.
    glab.route("GET note", raw='{\r\n\r\n  "ok": true\r\n}')
    assert glab_mod.api("note") == {"ok": True}


def test_status_204_with_no_body_is_none(glab):
    glab.route("PUT d/1", raw="", status=204)
    assert glab_mod.api("d/1", method="PUT") is None


@pytest.mark.parametrize(
    "status,reason,retryable",
    [
        (403, "forbidden", False),
        (404, "not-found", False),
        (409, "conflict", False),
        (500, "unknown", True),
        (503, "unknown", True),
        (418, "unknown", False),
    ],
)
def test_http_error_carries_status_reason_and_retryable(glab, status, reason, retryable):
    glab.route("GET user", {"message": f"{status} nope"}, status=status)
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status == status
    assert excinfo.value.reason == reason
    assert excinfo.value.retryable is retryable
    assert excinfo.value.exit_code == 5


def test_error_without_a_parseable_status_is_network(glab):
    # 등록되지 않은 경로는 HTTP 실패가 아니라 프로세스 실패다. 상태를 모른다.
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status is None
    assert excinfo.value.reason == "network"
    assert excinfo.value.retryable is True


def test_non_json_error_body_does_not_crash(glab):
    # 리버스 프록시가 HTML 에러 페이지를 돌려줄 수 있다.
    glab.route("GET user", raw="<html>502 Bad Gateway</html>", status=502)
    with pytest.raises(GlabError) as excinfo:
        glab_mod.api("user")
    assert excinfo.value.status == 502
```

그리고 **`test_check_false_returns_none` 함수를 삭제한다** — `check=` 가 이 과제에서 사라진다.

`cli/tests/test_mr.py`의 기존 `test_draft_notes_available_is_true` 아래에 추가:

```python
def test_draft_notes_unavailable_on_404(glab):
    # 이 GitLab 이 draft notes 를 지원하지 않는 경우.
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/draft_notes",
        {"message": "404 Not found"},
        status=404,
    )
    assert mr.draft_notes_available(1234) is False


def test_draft_notes_unavailable_on_server_error(glab):
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/draft_notes",
        {"message": "502 Bad Gateway"},
        status=502,
    )
    assert mr.draft_notes_available(1234) is False
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd cli && ./.venv/bin/python -m pytest tests/test_glab.py -q
```

Expected: FAIL with `ImportError: cannot import name 'GlabError' from 'mrq.errors'`

- [ ] **Step 3: `GlabError`를 만든다**

`cli/src/mrq/errors.py`의 `NetworkError` 클래스 **바로 뒤**에 추가:

```python
class GlabError(NetworkError):
    """`glab api` 호출 실패. HTTP 상태를 함께 나른다.

    `reason` 과 `retryable` 은 `docs/spec/data-model.md` §4.8 의 `local.push_error`
    가 그대로 쓰는 값이다. 소비자가 `message` 문자열을 파싱하게 만들지 않는다.
    """

    _REASONS = {403: "forbidden", 404: "not-found", 409: "conflict"}

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.reason = "network" if status is None else self._REASONS.get(status, "unknown")
        # "시간이 지나면 같은 요청이 성공할 수 있는가" 로 정한다. 403·404·409 는
        # 다시 보내도 같은 결과다 — 참으로 표시하면 에이전트가 루프를 돈다.
        self.retryable = status is None or status >= 500
```

- [ ] **Step 4: `api()`가 `-i`를 붙이고 상태를 읽게 한다**

`cli/src/mrq/glab.py`를 아래로 **전체 교체**한다.

```python
"""`glab api` 서브프로세스 래퍼.

인증·호스트 설정·토큰 저장소를 전부 glab 에 위임한다. HTTP 클라이언트를 쓰지 않는다
(docs/spec/cli.md §3).
"""

from __future__ import annotations

import json
import re
import subprocess
from typing import Any

from mrq.errors import GlabError

_STATUS_LINE = re.compile(r"^HTTP/[\d.]+\s+(\d{3})")


def api(
    path: str,
    *,
    method: str = "GET",
    fields: dict[str, str] | None = None,
    body: tuple[str, str] | None = None,
    paginate: bool = False,
) -> Any:
    """`glab api` 를 호출해 파싱된 JSON 을 돌려준다.

    `path` 에 `:fullpath` 플레이스홀더를 그대로 쓴다. glab 이 체크아웃 기준으로
    확장하므로 remote URL 을 파싱하지 않는다.

    `body=(필드명, 텍스트)` 는 `-F <필드명>=@-` 로 stdin 으로 보낸다. 긴 답글을
    인자로 넘기면 길이 제한과 셸 인용 문제가 생긴다. glab 은 `@` 로 읽은 값을
    **문자열로** 다루므로 `{` 로 시작하는 답글이 JSON 으로 재해석되지 않는다.

    실패하면 `GlabError` 를 던진다 — 상태 코드가 필요한 곳은 실패할 때뿐이고,
    `(status, data)` 튜플은 확인을 빼먹어도 조용히 통과하는 모양을 만든다
    (결정 0010).
    """
    args = ["glab", "api", path, "--method", method]
    for key, value in (fields or {}).items():
        args += ["-F", f"{key}={value}"]
    if body is not None:
        args += ["-F", f"{body[0]}=@-"]
    if paginate:
        args += ["--paginate", "--output", "ndjson"]
    else:
        # 상태 코드를 읽기 위한 응답 헤더. `--paginate` 와 같이 쓰면 glab 이
        # 페이지마다 헤더 블록을 내 ndjson 파싱이 깨진다 (1.114 실측). 그
        # 경로는 상태 코드를 쓰지 않는 유일한 경로라 붙이지 않는다.
        args.append("-i")

    proc = subprocess.run(
        args,
        input=body[1] if body is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    status, payload = _split(proc.stdout)

    if proc.returncode != 0:
        raise GlabError(f"glab api {path} 실패: {proc.stderr.strip()}", status=status)

    if paginate:
        return [json.loads(line) for line in payload.splitlines() if line.strip()]
    return json.loads(payload) if payload.strip() else None


def _split(out: str) -> tuple[int | None, str]:
    """`-i` 출력을 `(상태, 본문)` 으로 쪼갠다.

    실측(glab 1.114): 상태줄은 LF 로, 헤더는 CRLF 로 끝나고 본문 구분자는
    CRLFCRLF 다. LF LF 도 받아들여 glab 이 형식을 바꿔도 본문을 잃지 않는다.
    상태줄이 없으면(`-i` 를 안 붙인 paginate 경로) 전체가 본문이다.

    **첫** 구분자에서만 자른다. 본문이 빈 줄을 담고 있어도 잃지 않는다.
    """
    match = _STATUS_LINE.match(out)
    if match is None:
        return None, out
    status = int(match[1])
    for separator in ("\r\n\r\n", "\n\n"):
        index = out.find(separator)
        if index != -1:
            return status, out[index + len(separator) :]
    return status, ""
```

- [ ] **Step 5: 하네스가 헤더와 상태를 내게 한다**

`cli/tests/bin/glab`의 `_body` 함수 **아래**에 두 함수를 더한다.

```python
# 실물에서 받은 상태 문구. 진짜 glab 이 내는 모양에 가깝게 둔다.
_REASON_PHRASE = {
    200: "OK",
    201: "Created",
    204: "No Content",
    403: "Forbidden",
    404: "Not Found",
    409: "Conflict",
    418: "I'm a teapot",
    500: "Internal Server Error",
    502: "Bad Gateway",
    503: "Service Unavailable",
}


def _header_block(status: int) -> str:
    """진짜 glab 이 내는 바이트 모양 그대로.

    상태줄은 LF 로, 헤더는 CRLF 로 끝나고 마지막 헤더의 CRLF 와 빈 줄의 CRLF 가
    합쳐져 CRLFCRLF 구분자가 된다 (1.114 실측).
    """
    headers = (
        "Content-Type: application/json",
        "Gitlab-Lb: haproxy-main-20-lb-gprd",
        "X-Request-Id: fake-request-id",
    )
    status_line = f"HTTP/2.0 {status} {_REASON_PHRASE.get(status, '')}".rstrip() + "\n"
    return status_line + "".join(f"{header}\r\n" for header in headers) + "\r\n"


def _message(body: str, status: int) -> str:
    """에러 본문에서 사람이 읽을 메시지를 뽑는다. JSON 이 아니어도 터지지 않는다."""
    try:
        parsed = json.loads(body)
    except (ValueError, TypeError):
        return f"HTTP {status}"
    if isinstance(parsed, dict) and isinstance(parsed.get("message"), str):
        return parsed["message"]
    return f"HTTP {status}"
```

그리고 `main()`의 마지막 두 줄

```python
    sys.stdout.write(_body(fixtures, response))
    return 0
```

을 아래로 바꾼다.

```python
    status = response.get("status", 200)
    body = _body(fixtures, response)
    include = "-i" in argv or "--include" in argv

    sys.stdout.write((_header_block(status) if include else "") + body)

    if status >= 400:
        print(f"glab: {_message(body, status)} (HTTP {status})", file=sys.stderr)
        return 1
    return 0
```

- [ ] **Step 6: `draft_notes_available`을 고친다**

`cli/src/mrq/mr.py`의 임포트를 바꾼다:

```python
from mrq.errors import GlabError, MrDetectionError
```

그리고 `draft_notes_available` 전체를 아래로 바꾼다.

```python
def draft_notes_available(iid: int) -> bool:
    """가용성을 탐지만 한다. 미지원이면 `--draft` 를 명시적으로 거부한다.

    404(이 GitLab 이 지원하지 않음)와 네트워크 장애를 지금은 똑같이 False 로
    접는다. `GlabError.status` 로 구분할 수단은 생겼고, 구분해서 무엇을 할지는
    `--draft` 를 만드는 12 단계의 몫이다.
    """
    try:
        glab.api(f"{PROJECT}/merge_requests/{iid}/draft_notes")
    except GlabError:
        return False
    return True
```

- [ ] **Step 7: 남은 실패 하나를 고친다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
```

`test_get_builds_expected_argv`가 argv에 `-i`가 늘어 실패한다. 아래로 고친다.

```python
def test_get_builds_expected_argv(glab):
    glab.route("GET user", {"id": 7})
    glab_mod.api("user")
    assert glab.calls()[0]["argv"] == ["api", "user", "--method", "GET", "-i"]
```

- [ ] **Step 8: 전부 통과하는지 보고 커밋한다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
```

Expected: **363 passed** (349 + 13 신규 glab − 1 삭제 + 2 신규 mr)

```bash
cd /home/bongya/workspace/mrq/cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd /home/bongya/workspace/mrq && git add -A && git commit -F - <<'EOF'
R3: api() 가 HTTP 상태를 GlabError 에 실어 던진다

local.push_error.status (data-model.md §4.8) 를 채우려면 403 과 404 와
네트워크 장애를 구분해야 하는데, 지금 래퍼는 셋을 모두 NetworkError 나
None 으로 접는다.

paginate=False 일 때 -i 를 붙여 첫 줄에서 상태를 읽는다. paginate 에는
붙이지 않는다 — glab 이 페이지마다 헤더 블록을 내 ndjson 파싱이 깨지고
(1.114 실측), 하필 그 경로가 상태 코드를 쓰지 않는 유일한 경로다.

튜플이 아니라 예외로 나르는 이유는 상태가 필요한 곳이 실패할 때뿐이기
때문이다. (status, data) 는 호출처를 전부 언패킹으로 바꾸면서 확인을
빼먹어도 조용히 통과하는 자리를 만든다. GlabError 가 NetworkError 를
상속하므로 종료 코드 5 계약은 그대로다.

check=False 도 함께 없앴다. "호출 실패" 와 "성공했지만 본문이 비었음" 을
모두 None 으로 접던 인자이고, 유일한 사용처인 draft_notes_available 이
이제 GlabError 를 받는다.

가짜 glab 은 진짜 glab 의 바이트 모양을 낸다 — 상태줄은 LF, 헤더는
CRLF, 구분자는 CRLFCRLF, 비2xx 면 exit 1 + stderr 에
"glab: <msg> (HTTP <code>)".

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 3: `query` 매개변수와 `mr.detect`

**Files:**
- Modify: `cli/src/mrq/glab.py`
- Modify: `cli/src/mrq/mr.py` (`detect` 안의 검색 호출)
- Modify: `cli/tests/test_mr.py` (`SEARCH` 상수)
- Modify: `cli/tests/test_pull.py` (`SEARCH` 상수)
- Test: `cli/tests/test_glab.py`, `cli/tests/test_mr.py`

**Interfaces:**
- Consumes: Task 2의 `glab.api(path, *, method, fields, body, paginate)`
- Produces: `glab.api(..., query: dict[str, str] | None = None)` — `-f key=value`로 나가며 `method`가 `GET`/`DELETE`가 아니면 `ValueError`

- [ ] **Step 1: 실패 테스트를 쓴다**

`cli/tests/test_glab.py` 끝에 추가:

```python
def test_query_becomes_raw_field_flags_on_get(glab):
    glab.route("GET merge_requests", [])
    glab_mod.api("merge_requests", query={"state": "opened", "per_page": "100"})
    argv = glab.calls()[0]["argv"]
    assert "-f" in argv
    assert "state=opened" in argv
    assert "per_page=100" in argv
    # 경로에는 쿼리가 섞이지 않는다 — glab 이 퍼센트 인코딩을 한다.
    assert argv[1] == "merge_requests"


def test_query_keeps_special_characters_out_of_the_path(glab):
    # `#` 를 경로에 보간하면 프래그먼트로 잘려 그 뒤의 파라미터가 통째로
    # 사라진다 (1.114 실측).
    glab.route("GET merge_requests", [])
    glab_mod.api("merge_requests", query={"source_branch": "feat/#123", "state": "opened"})
    argv = glab.calls()[0]["argv"]
    assert "source_branch=feat/#123" in argv
    assert "state=opened" in argv


def test_query_value_containing_equals_is_passed_whole(glab):
    # glab 은 첫 `=` 에서만 쪼갠다. 값 안의 `=` 는 값의 일부다.
    glab.route("GET search", [])
    glab_mod.api("search", query={"q": "a=b", "empty": ""})
    argv = glab.calls()[0]["argv"]
    assert "q=a=b" in argv
    assert "empty=" in argv


def test_query_on_non_get_method_is_rejected(glab):
    # GET/DELETE 가 아니면 -f 는 JSON 본문으로 간다. 조용히 틀린 요청이 된다.
    with pytest.raises(ValueError):
        glab_mod.api("notes", method="POST", query={"a": "b"})
```

`cli/tests/test_mr.py` 끝에 추가:

```python
def test_detect_handles_special_characters_in_branch_name(git_repo, commit, glab):
    import subprocess

    commit({"a.py": "x\n"})
    branch = "feat/#123&x%y+z"
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=git_repo, check=True)
    glab.route("GET projects/:fullpath/merge_requests", [{**MR_1234, "source_branch": branch}])

    info = mr.detect(git_repo)

    assert info.iid == 1234
    # 쿼리가 경로에 보간되지 않았다. 보간하면 `#` 뒤가 잘려 state 와 per_page
    # 까지 사라지고 닫힌 MR 이 후보에 들어온다.
    argv = glab.calls()[0]["argv"]
    assert argv[1] == "projects/:fullpath/merge_requests"
    assert f"source_branch={branch}" in argv
    assert "state=opened" in argv
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd cli && ./.venv/bin/python -m pytest tests/test_glab.py tests/test_mr.py -k "query or special" -v
```

Expected: FAIL with `TypeError: api() got an unexpected keyword argument 'query'`

- [ ] **Step 3: `api()`에 `query`를 더한다**

`cli/src/mrq/glab.py`의 `_STATUS_LINE` 아래에 추가:

```python
# `-f` 는 GET/DELETE 에서만 URL 쿼리가 된다. 다른 메서드에서는 JSON 본문으로
# 간다 (1.114 실측 · 공식 문서).
_QUERY_METHODS = frozenset({"GET", "DELETE"})
```

시그니처의 `method` 바로 뒤에 더한다:

```python
    query: dict[str, str] | None = None,
```

docstring 끝에 한 문단을 더한다:

```
    `query` 는 URL 쿼리 파라미터다. 경로에 보간하면 안 된다 — 브랜치 이름의 `#`
    가 프래그먼트로 잘려 그 뒤의 파라미터까지 통째로 사라진다. glab 이 퍼센트
    인코딩을 한다.
```

함수 본문의 `args = [...]` 줄 **앞**에 가드를, 뒤에 `-f` 루프를 넣는다:

```python
    if query and method not in _QUERY_METHODS:
        raise ValueError(
            f"query 는 {'/'.join(sorted(_QUERY_METHODS))} 에서만 쓴다 (method={method}). "
            "다른 메서드에서 -f 는 JSON 본문으로 간다."
        )

    args = ["glab", "api", path, "--method", method]
    for key, value in (query or {}).items():
        # `-f`(--raw-field) 다. `-F` 는 `100` 을 정수로, `[` 로 시작하는 값을
        # 배열로 바꾼다 — 쿼리 값은 전부 문자열이어야 한다.
        args += ["-f", f"{key}={value}"]
    for key, value in (fields or {}).items():
        args += ["-F", f"{key}={value}"]
```

- [ ] **Step 4: `mr.detect`를 고친다**

`cli/src/mrq/mr.py`의

```python
    found = glab.api(f"{PROJECT}/merge_requests?source_branch={branch}&state=opened&per_page=100")
```

을 아래로 바꾼다.

```python
    found = glab.api(
        f"{PROJECT}/merge_requests",
        query={"source_branch": branch, "state": "opened", "per_page": "100"},
    )
```

- [ ] **Step 5: 라우트 키를 고친다**

쿼리가 경로에서 빠졌으므로 가짜 glab의 라우트 키도 짧아진다. 이것은 R3이 의도한 변경이다 — Task 1의 "기존 테스트를 수정하지 않는다"는 **하네스** 계약에 대한 것이었다.

`cli/tests/test_mr.py`의 `SEARCH` 상수:

```python
SEARCH = "GET projects/:fullpath/merge_requests"
```

`cli/tests/test_pull.py`의 `SEARCH` 상수:

```python
SEARCH = "GET projects/:fullpath/merge_requests"
```

`test_explicit_iid_skips_search`는 `call["argv"][1]`에 `source_branch=`가 없는 것을 단언한다. 쿼리가 경로에서 빠졌으므로 그 단언은 이제 항상 참이다 — 의미를 되살리려면 argv 전체를 보게 바꾼다.

```python
def test_explicit_iid_skips_search(repo_on_branch, glab):
    glab.route("GET projects/:fullpath/merge_requests/1234", MR_1234)
    assert mr.detect(repo_on_branch, explicit_iid=1234).iid == 1234
    assert all(
        not any(arg.startswith("source_branch=") for arg in call["argv"])
        for call in glab.calls()
    )
```

- [ ] **Step 6: 전부 통과하는지 보고 커밋한다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
```

Expected: **368 passed** (363 + 4 glab + 1 mr)

```bash
cd /home/bongya/workspace/mrq/cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd /home/bongya/workspace/mrq && git add -A && git commit -F - <<'EOF'
R3: 쿼리 파라미터를 경로에 보간하지 않는다

mr.detect 가 브랜치 이름을 경로에 그대로 끼워 넣고 있었다. `#` 를 담은
적법한 브랜치 이름이 프래그먼트로 잘리는데, 잘리는 것이 source_branch
하나가 아니다 — 그 뒤의 state=opened 와 per_page=100 도 함께 사라져
닫힌·머지된 MR 까지 후보에 들어온다. 실측:

  지금:  ...merge_requests?source_branch=feat/
  -f:    ...merge_requests?per_page=100&source_branch=feat%2F%23123&state=opened

query 는 -f(--raw-field), fields 는 -F(--field) 로 나간다. 쿼리 값은
전부 문자열이어야 하는데 -F 는 100 을 정수로, `[` 로 시작하는 값을
배열로 바꾼다. GET/DELETE 가 아닌 메서드에서 -f 는 JSON 본문으로 가므로
ValueError 로 막는다.

잔여 항목 문서는 "fields 로 대체할 수 없다" 고 적었는데 틀렸다.
--method 없이 필드를 붙이면 glab 이 요청을 POST 로 바꾸기 때문에 그렇게
보였을 것이다. api() 는 이미 항상 --method 를 넘긴다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 4: 다중 페이지 응답

`testing.md` §3이 "2페이지 이상 응답 (ndjson 스트리밍)" 픽스처를 요구하는데, 하네스가 파일 하나를 뱉으므로 "2페이지"와 "한 페이지 N줄"이 구분되지 않아 빠져 있었다.

**Files:**
- Modify: `cli/tests/bin/glab`
- Create: `cli/tests/fixtures/discussions-page0.ndjson`
- Create: `cli/tests/fixtures/discussions-page1.ndjson`
- Modify: `cli/tests/test_pull.py` (`pullable` 픽스처)
- Test: `cli/tests/test_glab.py`

**Interfaces:**
- Consumes: Task 1의 `Harness.route(key, pages=[...])`, `routes.json`의 `{"pages": [...]}`
- Produces: 없음

- [ ] **Step 1: 실패 테스트를 쓴다**

`cli/tests/test_glab.py` 끝에 추가:

```python
def test_paginate_concatenates_pages_in_order(glab):
    glab.route("GET discussions", pages=['{"id": "a"}\n{"id": "b"}\n', '{"id": "c"}\n'])
    assert glab_mod.api("discussions", paginate=True) == [
        {"id": "a"},
        {"id": "b"},
        {"id": "c"},
    ]


def test_without_paginate_only_the_first_page_is_returned(glab):
    # 진짜 glab 도 --paginate 없이는 1 페이지만 준다. 하네스가 전부 주면
    # "페이지네이션을 빠뜨린 코드" 가 테스트를 통과해 버린다.
    glab.route("GET discussions", pages=['[{"id": "a"}]', '[{"id": "c"}]'])
    assert glab_mod.api("discussions") == [{"id": "a"}]
```

- [ ] **Step 2: 실패를 확인한다**

```bash
cd cli && ./.venv/bin/python -m pytest tests/test_glab.py -k page -q
```

Expected: FAIL — `pages` 응답에 `file`도 `body`도 없어 본문이 빈 문자열이 되고 `[]`가 돌아온다.

- [ ] **Step 3: 하네스가 `pages`를 읽게 한다**

`cli/tests/bin/glab`의 `_body`를 아래로 바꾼다.

```python
def _body(fixtures: Path, response: dict, paginate: bool) -> str:
    if "pages" in response:
        pages = _pages(fixtures, response)
        # --paginate 가 없으면 진짜 glab 도 1 페이지만 준다.
        return "".join(pages) if paginate else pages[0]
    if "file" in response:
        return (fixtures / response["file"]).read_text(encoding="utf-8")
    return response.get("body", "")


def _pages(fixtures: Path, response: dict) -> list[str]:
    return [(fixtures / name).read_text(encoding="utf-8") for name in response["pages"]]
```

- [ ] **Step 4: 헤더가 페이지마다 나오게 한다**

`main()`에서 Task 2가 넣은 세 줄

```python
    status = response.get("status", 200)
    body = _body(fixtures, response)
    include = "-i" in argv or "--include" in argv

    sys.stdout.write((_header_block(status) if include else "") + body)
```

을 아래로 바꾼다.

```python
    status = response.get("status", 200)
    paginate = "--paginate" in argv
    body = _body(fixtures, response, paginate)
    include = "-i" in argv or "--include" in argv

    if include and paginate and "pages" in response:
        # 진짜 glab 은 페이지마다 헤더 블록을 낸다 (1.114 실측). api() 는 이
        # 조합을 보내지 않지만(cli.md §3), 하네스가 조용히 잘 처리하면
        # 나중에 누가 paginate 경로에 -i 를 붙였을 때 실제 GitLab 에서만
        # 깨진다. 실물과 똑같이 깨뜨려 테스트가 잡게 한다.
        sys.stdout.write(
            "".join(_header_block(status) + page for page in _pages(fixtures, response))
        )
    else:
        sys.stdout.write((_header_block(status) if include else "") + body)
```

- [ ] **Step 5: 2페이지 픽스처를 만든다**

```bash
cd /home/bongya/workspace/mrq && python3 - <<'PY'
from pathlib import Path

src = Path("cli/tests/fixtures/discussions.ndjson")
lines = [line for line in src.read_text(encoding="utf-8").splitlines() if line.strip()]
half = len(lines) // 2
Path("cli/tests/fixtures/discussions-page0.ndjson").write_text(
    "\n".join(lines[:half]) + "\n", encoding="utf-8"
)
Path("cli/tests/fixtures/discussions-page1.ndjson").write_text(
    "\n".join(lines[half:]) + "\n", encoding="utf-8"
)
print(f"page0={half} page1={len(lines) - half}")
PY
```

Expected: `page0=4 page1=5`

`discussions.ndjson`은 **지우지 않는다** — `test_discussions.py`와
`test_pull_drops_threads_removed_on_server`가 단일 응답으로 쓴다.

- [ ] **Step 6: `pull`이 2페이지를 지나가게 한다**

`cli/tests/test_pull.py`의 `pullable` 픽스처에서

```python
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        raw=(FIXTURES / "discussions.ndjson").read_text(encoding="utf-8"),
    )
```

을 아래로 바꾼다.

```python
    # 2 페이지로 나눠 등록한다. 한 페이지 N 줄과 구분되는 유일한 모양이고
    # testing.md §3 이 요구한다.
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        pages=[
            (FIXTURES / "discussions-page0.ndjson").read_text(encoding="utf-8"),
            (FIXTURES / "discussions-page1.ndjson").read_text(encoding="utf-8"),
        ],
    )
```

- [ ] **Step 7: 전부 통과하는지 보고 커밋한다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
```

Expected: **370 passed** (368 + 2). `pull`의 스레드 수 단언(8)이 그대로여야 한다 — 바뀌면 분할이 줄을 잃은 것이다.

```bash
cd /home/bongya/workspace/mrq/cli && ./.venv/bin/ruff format . && ./.venv/bin/ruff check --fix .
cd /home/bongya/workspace/mrq && git add -A && git commit -F - <<'EOF'
R4: 하네스가 다중 페이지 응답을 표현한다

testing.md §3 이 "2 페이지 이상 응답" 픽스처를 요구하는데 하네스가 파일
하나를 뱉으므로 "2 페이지" 와 "한 페이지 N 줄" 이 구분되지 않아 빠져
있었다. 라우트에 pages 를 주면 --paginate 일 때 이어 붙이고, 없으면
진짜 glab 처럼 1 페이지만 준다 — 전부 주면 페이지네이션을 빠뜨린 코드가
테스트를 통과한다.

-i 와 함께면 페이지마다 헤더 블록을 낸다. api() 는 그 조합을 보내지
않지만, 하네스가 조용히 잘 처리하면 나중에 누가 붙였을 때 실제
GitLab 에서만 깨진다.

pull 테스트가 이제 2 페이지 응답을 지나간다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## Task 5: 문서 이관

설계 문서와 이 계획서를 지우고 내용을 규범·결정으로 옮긴다 (CLAUDE.md의 작업 방식).

**Files:**
- Modify: `docs/spec/cli.md` (§3)
- Modify: `docs/spec/testing.md` (§2, §3)
- Create: `docs/decisions/0010-glab-status-via-exception.md`
- Modify: `docs/plans/README.md`
- Modify: `docs/plans/2026-10-12-cli-core-residuals.md`
- Modify: `CLAUDE.md` (테스트 개수)
- Delete: `docs/plans/2026-10-13-glab-api-and-harness-design.md`, `docs/plans/2026-10-13-glab-api-and-harness.md`

**Interfaces:**
- Consumes: Task 1~4의 최종 동작
- Produces: 없음

- [ ] **Step 1: `spec/cli.md` §3을 고친다**

"### 알려진 공백: `api()` 는 HTTP 상태를 돌려주지 않는다" 절 **전체**를 아래로 교체한다.

```markdown
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

**`--paginate` 에는 `-i` 를 붙이지 않는다**(MUST NOT). glab 이 페이지마다 헤더
블록을 내 ndjson 파싱이 깨진다. 그 경로(`pull` 의 discussions)는 상태 코드를 쓰지
않는 유일한 경로이고, 거기서 실패하면 `status` 는 `null`, `reason` 은 `network`
다. `reason` 의 소비자는 `local.push_error` 뿐이고 `push` 는 paginate 를 쓰지
않으므로 틀린 `reason` 이 기록으로 남을 경로가 없다.
```

- [ ] **Step 2: `spec/testing.md` §2에 하네스 계약을 더한다**

"### 타임존을 고정한다" 절 **앞**에 삽입한다.

~~~markdown
### `routes.json` 계약

라우트 값은 **응답 목록**이다. 같은 키로 들어온 호출의 순서대로 소비하고, 목록이
소진되면 마지막 것이 반복된다 — 크래시 복구 테스트가 같은 명령을 재실행하므로
소진을 에러로 만들면 하네스 때문에 실패한다. 호출 수는 **경로별로** 센다.

```jsonc
{
  "GET projects/:fullpath/merge_requests/1234/discussions": [
    { "status": 200, "pages": ["p0.ndjson", "p1.ndjson"] }
  ],
  "POST .../discussions/abc/notes": [
    { "status": 201, "file": "r3.json" },
    { "status": 403, "body": "{\"message\":\"403 Forbidden\"}" }
  ]
}
```

### 가짜 glab 은 진짜 glab 이 내는 것을 낸다

"우리 파서가 읽기 쉬운 것"을 내면 안 된다(MUST NOT). 어긋나면 실제 GitLab 에서만
깨지는 코드가 테스트를 통과한다.

- `-i` 가 argv 에 있을 때만 헤더를 낸다. **상태줄은 LF, 헤더는 CRLF, 구분자는
  CRLFCRLF** (glab 1.114 실측)
- `-i` 와 `--paginate` 가 함께면 **페이지마다** 헤더 블록을 낸다
- `--paginate` 가 없으면 `pages` 중 **첫 페이지만** 준다
- `status >= 400` 이면 exit 1, stdout 에 에러 본문, stderr 에
  `glab: <메시지> (HTTP <코드>)`

`MRQ_GLAB_FAIL_AT` 은 HTTP 실패가 아니라 **프로세스 사망**을 흉내 내는 별개의
장치다. §6 의 "N 번째 호출에서 사망" 이 그것을 쓴다. 죽은 호출도 응답 목록을
소비한 것으로 센다 — "요청은 갔는데 그 뒤에 죽었다" 가 크래시 복구가 다루는
모양이다.
~~~

- [ ] **Step 3: `spec/testing.md` §3의 픽스처 목록을 고친다**

"- 2페이지 이상 응답 (ndjson 스트리밍)" 줄을 아래로 바꾼다.

```markdown
- 2페이지 이상 응답 (ndjson 스트리밍) — `discussions-page0.ndjson` /
  `discussions-page1.ndjson`. 라우트에 `pages` 로 등록한다
```

- [ ] **Step 4: 결정 0010을 쓴다**

`docs/decisions/0010-glab-status-via-exception.md`:

```markdown
# 0010. `glab.api` 의 HTTP 상태를 튜플이 아니라 예외로 나른다

날짜: 2026-10-13 · 상태: 채택 (잔여 항목 R3 의 `(status: int, data: Any)` 제안을
대체)

## 배경

`local.push_error.status`(`data-model.md` §4.8)를 채우려면 403 과 404 와 네트워크
장애를 구분해야 한다. 당시 래퍼는 성공 시 파싱된 JSON, 실패 시 `NetworkError`
(또는 `check=False` 면 `None`)만 주어 셋을 구분할 수 없었다.

잔여 항목 문서와 `cli.md` §3 은 `api()` 를 `(status, data)` 로 바꾸는 것을
제안했다. "실패"와 "성공했지만 본문이 비었음"의 모호성도 함께 해소된다는 것이
근거였다.

## 결정

**실패를 `GlabError(NetworkError)` 로 던지고 거기에 `status`·`reason`·`retryable`
을 싣는다.** 튜플도 결과 객체도 쓰지 않는다.

## 근거

**상태 코드가 필요한 곳은 실패할 때뿐이다.** 소비자는 `local.push_error` 하나이고,
성공 경로에서 상태를 읽는 호출처는 없다. 튜플은 그 하나를 위해 모든 호출처를
언패킹으로 바꾼다.

**그리고 그 호출처마다 "확인을 빼먹어도 조용히 통과하는" 자리를 만든다.**
`status, data = api(...)` 뒤에 `if status != 200` 을 빠뜨린 코드는 에러 본문을
정상 데이터로 다루고 그대로 흘러간다. 예외는 빼먹을 수 없다.

`NetworkError` 를 상속하므로 종료 코드 5 계약(`cli.md` §2)과 기존 호출처가
그대로다. `push` 만 `except GlabError` 로 받는다.

"성공했지만 본문이 비었음"의 모호성은 부수적으로 사라진다 — 실패가 예외가 되면
`None` 반환은 "성공했고 본문이 비었다" 하나만 뜻한다. 실측에서도 빈 성공 응답은
`[]` + exit 0 이었다.

## 대가

- `push` 가 스레드마다 `try/except` 를 쓴다. 스레드별로 결과를 즉시 json 에 쓰는
  구조(`cli.md` §9)와 모양이 맞으므로 비용으로 보지 않는다.
- `GlabError` 가 `reason` 매핑을 들고 있어 예외 계층에 로직이 한 조각 들어왔다.
  `data-model.md` §4.8 의 열거값과 한 곳에 묶여 있는 편이 흩어지는 것보다 낫다.

## 함께 확인한 것

같은 조사에서 잔여 항목 R3 의 전제 둘이 **틀린 것**으로 드러났다 (glab 1.114 실측).

- "`fields` 로 쿼리를 대체할 수 없다" — `--method` 가 명시된 GET 에서는 `-f` 가
  URL 쿼리가 된다. `--method` 없이 재면 glab 이 POST 로 바꾸므로 그렇게 보인다.
- "`--input` 과 `Content-Type` 이 필요하다" — 계획 3 의 페이로드는 전부 평평하고,
  중첩 객체조차 `-F 'position={…}'` 로 보낼 수 있다. 415 와 bracket 키 함정은
  위치 코멘트를 **새로 만들** 때의 문제다.
```

- [ ] **Step 5: 잔여 항목 문서를 갱신한다**

`docs/plans/2026-10-12-cli-core-residuals.md`에서 **R3 과 R4 문단을 통째로 삭제**하고, R3에 있던 `--input`/`Content-Type`/bracket 키 내용을 "## 코드 모양" 절 **앞**에 아래 절로 옮긴다.

```markdown
## 위치 코멘트를 새로 만들 때 필요한 것 (future work)

`mrq` 는 기존 스레드에 답글만 단다. 새 위치 코멘트를 만드는 기능
(`mrq-design.md` §6 의 future work)을 할 때 아래가 걸린다. 2026-10-13 실측이다.

- `-F "position[new_line]=15"` 식 bracket 키는 JSON 본문에서 중첩으로 가지
  않는다. glab 1.114 는 조용히 무시했고(위치 없는 스레드가 성공 응답과 함께
  만들어진다), 최신 문서는 에러로 거부한다고 적는다. 어느 쪽이든 쓰면 안 된다.
- 중첩은 `-F 'position={"position_type":"text","new_line":15}'` 로 보낸다.
  `--input` 은 필요 없다.
- `--input` 을 쓴다면 `-H "Content-Type: application/json"` 을 함께 줘야 한다.
  빼면 GitLab 이 `HTTP 415` 를 돌려준다.
```

머리말의 "**R6(멀티라인 앵커)과 R7(UTC 렌더)은 브랜치 `jbseo/pre_step3`에서 해소됐다.**" 문단 뒤에 더한다.

```markdown
**R3·R4도 같은 브랜치에서 해소됐다.** 규범은 `spec/cli.md` §3 과
`spec/testing.md` §2 에, 결정은
[0010](../decisions/0010-glab-status-via-exception.md)에 있다. 그 조사에서 R3 의
전제 둘(쿼리 직렬화, `--input` 필요성)이 틀렸던 것도 0010 에 기록했다.
```

- [ ] **Step 6: `docs/plans/README.md`를 갱신한다**

"## 계획 3 전 과제 (진행 중)" 제목을 "## 계획 3 전 과제 — 완료"로 바꾸고, 표의 R3·R4 행 상태를 `완료`로 채운다. 로드맵 표(문서 상단)의 전 과제 행도 바꾼다.

```markdown
| — | — | **계획 3 전 과제** — 잔여 항목 R6·R7·R3·R4 | **완료** (2026-10-13) |
```

- [ ] **Step 7: 설계 문서와 계획서를 지우고 테스트 개수를 갱신한다**

```bash
cd /home/bongya/workspace/mrq
rm docs/plans/2026-10-13-glab-api-and-harness-design.md
rm docs/plans/2026-10-13-glab-api-and-harness.md
```

`CLAUDE.md`의 `# 전체 (346개)`를 `# 전체 (370개)`로 바꾼다.

- [ ] **Step 8: 완료 조건을 확인하고 커밋한다**

```bash
cd cli && ./.venv/bin/python -m pytest -q
cd cli && ./.venv/bin/ruff format --check . && ./.venv/bin/ruff check .
cd /home/bongya/workspace/mrq && grep -rn "check=False\|source_branch={" cli/src/ || echo "(없음 — 정상)"
ls docs/plans/
```

Expected: 370 passed · 린트 통과 · grep 결과 없음 · `docs/plans/`에 `README.md`와 `2026-10-12-cli-core-residuals.md`만

```bash
cd /home/bongya/workspace/mrq && git add -A && git commit -F - <<'EOF'
docs: R3·R4 를 스펙으로 옮기고 전 과제를 닫는다

규범:
- cli.md §3 — api() 의 계약(GlabError 의 status/reason/retryable), 쿼리를
  경로에 보간하지 않는 이유, -i 를 paginate 에 붙이지 않는 이유
- testing.md §2 — routes.json 계약과 "진짜 glab 이 내는 것을 낸다" 넷
- testing.md §3 — 2 페이지 픽스처가 더 이상 빠져 있지 않다

결정 0010 — 상태를 튜플이 아니라 예외로. 상태가 필요한 곳은 실패할
때뿐이고, 튜플은 모든 호출처에 "확인을 빼먹어도 조용히 통과하는" 자리를
만든다. 같은 조사에서 잔여 항목 R3 의 전제 둘이 틀린 것도 함께 기록했다.

잔여 항목 문서에서 R3·R4 를 지우고, --input/Content-Type/bracket 키는
위치 코멘트 생성(future work)의 선행 지식으로 옮겼다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>
EOF
```

---

## 완료 조건

- `cd cli && ./.venv/bin/python -m pytest` — 370개 통과
- `./.venv/bin/ruff format --check .` 과 `./.venv/bin/ruff check .` 통과
- `grep -rn "check=False\|source_branch={" cli/src/` 가 비어 있다
- `docs/plans/README.md`의 전 과제 표 네 행이 모두 완료
- `docs/plans/`에 이 계획서와 설계 문서가 남아 있지 않다
