"""`sync --prefer [ID=]md|json` 의 파싱과 해소. docs/spec/cli.md §5.

플래그 하나에 스코프 접두사를 **선택적으로** 붙인다 (`RUST_LOG=debug` 대
`RUST_LOG=mycrate=trace` 와 같은 모양). 플래그를 둘로 나누지 않는 이유는
`--prefer md` 의 값이 "일괄" 이 아니라 **"id 를 타이핑하지 않아도 된다"** 이기
때문이다 — 충돌 하나짜리 경우에도 그쪽이 낫고, 터미널의 사람과 AI 에이전트가
쓰는 경로다.

해소 규칙: **좁은 스코프가 순서와 무관하게 이긴다. 같은 스코프 안에서는 뒤가
이긴다.** 위치 기반 fold 가 아니다 — fold 는 "앞의 개별 지정을 뒤의 전역 항목이
지운다" 는 모서리를 만드는데, `chmod`·`.gitignore`·CSS·`RUST_LOG` 가 전부
반대로 동작하므로 반대로 기대하는 사람이 생긴다.

근거는 `docs/decisions/0013-scoped-conflict-resolution.md`.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass

from mrq.errors import UsageError

DIRECTIONS = ("md", "json")


@dataclass(frozen=True)
class Preference:
    """`--prefer` 한 개. `ref is None` 이면 스코프 없음(전체 기본값)."""

    ref: str | None
    direction: str


def parse(values: Sequence[str] | None) -> list[Preference]:
    """`--prefer` 값들을 `Preference` 리스트로. 문법 오류는 `UsageError`(exit 1).

    리뷰를 보지 않는다 — 접두사 해석과 불변식 가드는 `resolve` 의 몫이다.
    """
    return [_one(value) for value in values or ()]


def _one(value: str) -> Preference:
    ref: str | None = None
    direction = value
    if "=" in value:
        ref, _, direction = value.partition("=")
        if not ref:
            raise _bad(value)
    if direction not in DIRECTIONS:
        raise _bad(value)
    return Preference(ref, direction)


def _bad(value: str) -> UsageError:
    return UsageError(
        f"--prefer {value!r} 를 해석할 수 없습니다. "
        "`--prefer md`, `--prefer json`, 또는 `--prefer <스레드>=md|json` 형태로 주세요."
    )
