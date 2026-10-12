"""문자열 탐색 fallback. docs/spec/reanchoring.md §5.2.

git 라인 매핑이 실패했을 때만 쓴다. 주 전략이 아니다.
"""

from __future__ import annotations

from mrq import model

WINDOW = 50


def find(lines: list[str], anchor: model.Anchor, start_line: int | None) -> tuple[int, str] | None:
    """`(1-indexed 줄, confidence)` 또는 None."""
    if not lines:
        return None

    window = _window(lines, start_line)
    exact = [i for i in window if lines[i] == anchor.line]

    # 공백뿐인 앵커는 창 안에서 유일할 때만 받아들인다. strip 비교·context 점수·
    # 전체 탐색을 모두 건너뛴다 — 빈 줄 주변은 또 빈 줄이라 셋 다 근거를 잃는다.
    if not anchor.line.strip():
        return (exact[0] + 1, "exact") if len(exact) == 1 else None

    if len(exact) == 1:
        return exact[0] + 1, "exact"
    if len(exact) > 1:
        # 창 안에 완전 일치가 여럿이면 파일 전체에서도 유일할 수 없다.
        picked = _disambiguate(lines, exact, anchor)
        return (picked + 1, "fuzzy") if picked is not None else None

    target = anchor.line.strip()
    stripped = [i for i in window if lines[i].strip() == target]
    if len(stripped) == 1:
        return stripped[0] + 1, "fuzzy"
    if len(stripped) > 1:
        picked = _disambiguate(lines, stripped, anchor)
        if picked is not None:
            return picked + 1, "fuzzy"

    # 블록이 파일 안에서 멀리 옮겨진 경우. 유일성 가드가 오탐을 막는다.
    whole = [i for i, text in enumerate(lines) if text == anchor.line]
    if len(whole) == 1:
        return whole[0] + 1, "fuzzy"

    return None


def _window(lines: list[str], start_line: int | None) -> range:
    center = (start_line - 1) if start_line else 0
    return range(max(0, center - WINDOW), min(len(lines), center + WINDOW + 1))


def _score(lines: list[str], index: int, anchor: model.Anchor) -> int:
    """앞뒤 context 가 몇 줄 맞는지. 공백 차이는 무시한다."""
    score = 0
    for offset, expected in enumerate(reversed(anchor.context_before), start=1):
        position = index - offset
        if position >= 0 and lines[position].strip() == expected.strip():
            score += 1
    for offset, expected in enumerate(anchor.context_after, start=1):
        position = index + offset
        if position < len(lines) and lines[position].strip() == expected.strip():
            score += 1
    return score


def _disambiguate(lines: list[str], candidates: list[int], anchor: model.Anchor) -> int | None:
    scored = sorted(((_score(lines, i, anchor), i) for i in candidates), reverse=True)
    if scored[0][0] == 0:
        return None  # context 가 전혀 안 맞으면 근거가 없다
    if len(scored) >= 2 and scored[0][0] == scored[1][0]:
        return None  # 동점이면 추측하지 않는다
    return scored[0][1]
