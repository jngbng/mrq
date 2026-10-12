"""`glab api` 서브프로세스 래퍼.

인증·호스트 설정·토큰 저장소를 전부 glab 에 위임한다. HTTP 클라이언트를 쓰지 않는다
(docs/spec/cli.md §3).
"""

from __future__ import annotations

import json
import subprocess
from typing import Any

from mrq.errors import NetworkError


def api(
    path: str,
    *,
    method: str = "GET",
    fields: dict[str, str] | None = None,
    body: tuple[str, str] | None = None,
    paginate: bool = False,
    check: bool = True,
) -> Any:
    """`glab api` 를 호출해 파싱된 JSON 을 돌려준다.

    `path` 에 `:fullpath` 플레이스홀더를 그대로 쓴다. glab 이 체크아웃 기준으로
    확장하므로 remote URL 을 파싱하지 않는다.

    `body=(필드명, 텍스트)` 는 `-F <필드명>=@-` 로 stdin 으로 보낸다. 긴 답글을
    인자로 넘기면 길이 제한과 셸 인용 문제가 생긴다.
    """
    args = ["glab", "api", path, "--method", method]
    for key, value in (fields or {}).items():
        args += ["-F", f"{key}={value}"]
    if body is not None:
        args += ["-F", f"{body[0]}=@-"]
    if paginate:
        args += ["--paginate", "--output", "ndjson"]

    proc = subprocess.run(
        args,
        input=body[1] if body is not None else None,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    if proc.returncode != 0:
        if not check:
            return None
        raise NetworkError(f"glab api {path} 실패: {proc.stderr.strip()}")

    if paginate:
        return [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    return json.loads(proc.stdout) if proc.stdout.strip() else None
