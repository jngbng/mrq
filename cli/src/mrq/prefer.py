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
from dataclasses import dataclass, field

from mrq import threads
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


@dataclass
class Resolution:
    """해소 방향. `picks` 의 키는 **완전한** thread id 다."""

    default: str | None = None
    picks: dict[str, str] = field(default_factory=dict)

    def direction_for(self, thread_id: str) -> str | None:
        return self.picks.get(thread_id, self.default)

    def __bool__(self) -> bool:
        return self.default is not None or bool(self.picks)


def resolve(review, prefs: list[Preference]) -> Resolution:
    """`Preference` 들을 리뷰에 대조해 `Resolution` 으로 접는다.

    좁은 스코프가 순서와 무관하게 이기므로 전역과 개별을 **따로** 접는다.
    접두사 해석은 `threads.resolve_ref` 에 맡긴다 (`cli.md` §1 MUST) — 모호한
    접두사가 지정하지 않은 스레드에 방향을 적용하는 사고를 막는 자리다.
    """
    out = Resolution()
    for pref in prefs:
        if pref.ref is None:
            _guard_collision(review, pref.direction)
            out.default = pref.direction
        else:
            out.picks[threads.resolve_ref(review, pref.ref).id] = pref.direction
    return out


def _guard_collision(review, direction: str) -> None:
    """스코프 없는 값이 실제 스레드 접두사와 겹치면 거부한다.

    discussion id 는 SHA1 16진수(`[0-9a-f]`)이고 `md` 의 `m`, `json` 의
    `j`·`s`·`o`·`n` 은 16진수가 아니므로 도달할 수 없다. 그래도 막아 두는 이유는
    이 사실이 깨졌을 때 **조용한 오동작**(사용자가 지목한 스레드 대신 전체에
    방향이 걸린다)이 아니라 에러가 나게 하기 위해서다.
    """
    hit = [t.id for t in review.threads if t.id.startswith(direction)]
    if hit:
        raise UsageError(
            f"--prefer {direction!r} 가 스레드 id {', '.join(hit)} 의 접두사와 겹칩니다. "
            f"그 스레드만 지목하려면 `--prefer {hit[0]}={direction}` 처럼 주세요."
        )
