"""스레드 참조 해석. `docs/spec/cli.md` §1.

`<thread>` 인자(`reply`/`state`/`open --thread`)와 `sync --prefer <ID>=...` 의
스코프는 discussion id의 **유일한 접두사**를 허용해야 한다(MUST). 접두사가 여러
스레드에 걸리면 exit 1과 함께 후보를 보여준다. 이 판정을 한 곳에 모아 두는
이유는, 모호한 접두사가 사용자가 지정하지 않은 스레드에 해소 방향을 적용해 그
스레드의 CLI 값을 조용히 지우는 사고를 막기 위해서다.
"""

from __future__ import annotations

from mrq import model, render
from mrq.errors import UsageError


def resolve_ref(review: model.Review, ref: str) -> model.Thread:
    """`ref`를 `review.threads` 중 정확히 하나의 스레드로 해석한다.

    빈 문자열은 거부한다 — 접두사 매칭이 전체 스레드와 우연히 하나만 있는
    상태에서 그 하나를 "일치"로 돌려줄 수 있어 위험하다. 정확한 id 일치를
    먼저 보고, 그 다음 고유한 접두사를 본다. 후보가 0개거나 2개 이상이면
    `UsageError`(exit 1)로 끝낸다 — 빈 결과를 성공으로 보고하지 않는다
    (`cli.md` §2 MUST).
    """
    if not ref:
        raise UsageError("빈 스레드 id는 허용하지 않습니다.")
    for thread in review.threads:
        if thread.id == ref:
            return thread
    candidates = [t for t in review.threads if t.id.startswith(ref)]
    if not candidates:
        raise UsageError(f"스레드 {ref!r} 를 찾을 수 없습니다. `mrq list` 로 id 를 확인하세요.")
    if len(candidates) > 1:
        listing = ", ".join(
            f"{t.id} (@{t.notes[0].author if t.notes else '?'})" for t in candidates
        )
        raise UsageError(f"스레드 접두사 {ref!r} 가 {len(candidates)}개에 걸립니다 — {listing}")
    return candidates[0]


def filter_threads(
    threads: list[model.Thread],
    *,
    state: str | None = None,
    confidence: str | None = None,
    include_resolved: bool = False,
) -> list[model.Thread]:
    """`mrq list` 의 필터 (`cli.md` §7). 배열의 원소를 줄이기만 한다 — 필드를
    가공하지 않는다(MUST).

    `include_resolved=False`일 때 기본 가시성은 `render.visible`과 같은 규칙을
    쓴다(review-md.md §5 MUST) — 서버에서 resolve된 스레드도 전송하지 않은 작업
    (`local.reply`가 비어 있지 않거나 `local.state != todo`)이 있으면 보여야 한다.
    동료가 내 스레드를 먼저 resolve해도 아직 전송하지 않은 내 답글이 `list`에서만
    사라지면, 사람은 `review.md`에서 그 스레드를 보는데 AI 에이전트는 `list`로는
    보지 못하는 분열이 생긴다(`docs/decisions/0001-human-and-ai-are-peers.md`).
    정의를 하나만 두기 위해 `render.visible`을 그대로 재사용한다.
    """
    base = threads if include_resolved else render.visible(threads, include_resolved=False)
    out = []
    for thread in base:
        if state is not None and thread.local.state != state:
            continue
        if confidence is not None:
            if thread.location is None or thread.location.confidence != confidence:
                continue
        out.append(thread)
    return out
