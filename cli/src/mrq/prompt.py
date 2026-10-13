"""되돌릴 수 없는 작업 앞의 확인. `push` 와 `clean` 이 같은 규칙을 쓴다."""

from __future__ import annotations

import sys

from mrq.errors import UsageError


def confirm(message: str, *, force: bool) -> None:
    """바깥으로 나가고 되돌릴 수 없는 작업 앞의 확인 (`cli.md` §9·§11).

    비대화형(파이프·CI·AI 에이전트)에서는 묻지 않고 거부한다 — `input()` 이
    블로킹되면 세션이 멈추고, 그 침묵은 실패보다 나쁘다.

    프롬프트 문구는 stderr 에 찍는다(MUST) — `input(message)`로 넘기면 그
    문구가 **stdout** 에 찍혀 `--json` 을 쓰는 대화형 세션에서 `cli.md` §2 의
    "stdout 은 순수 JSON 객체 하나" 를 깬다. `input()` 자신에게는 프롬프트를
    주지 않고 빈 호출로 둔다.
    """
    if force:
        return
    if not sys.stdin.isatty():
        raise UsageError(f"{message} 비대화형 실행이므로 중단했습니다. `--force` 로 진행하세요.")
    print(f"{message} 계속할까요? [y/N] ", end="", file=sys.stderr)
    answer = input()
    if answer.strip().lower() not in ("y", "yes"):
        raise UsageError("중단했습니다.")
