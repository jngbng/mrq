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

# `-f` 는 GET/DELETE 에서만 URL 쿼리가 된다. 다른 메서드에서는 JSON 본문으로
# 간다 (1.114 실측 · 공식 문서).
_QUERY_METHODS = frozenset({"GET", "DELETE"})


def api(
    path: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
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

    `query` 는 URL 쿼리 파라미터다. 경로에 보간하면 안 된다 — 브랜치 이름의 `#`
    가 프래그먼트로 잘려 그 뒤의 파라미터까지 통째로 사라진다. glab 이 퍼센트
    인코딩을 한다.
    """
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
