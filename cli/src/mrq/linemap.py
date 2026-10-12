"""git diff 기반 경로 맵과 라인 맵.

재앵커링의 주 전략이다. 문자열 탐색은 이것이 실패했을 때의 fallback 이다
(docs/spec/reanchoring.md §4, §5.1).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from mrq import gitcmd

_HUNK = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@", re.MULTILINE)


@dataclass
class PathMap:
    renames: dict[str, str] = field(default_factory=dict)
    deleted: set[str] = field(default_factory=set)

    def resolve(self, path: str) -> str | None:
        """head_sha 기준 경로 → 작업 트리 경로. 삭제되었으면 None."""
        if path in self.deleted:
            return None
        return self.renames.get(path, path)


def path_map(root: Path, head_sha: str) -> PathMap:
    """`git diff -M --name-status <head_sha>` 로 rename/delete 맵을 만든다.

    pathspec 을 주면 -M 이 동작하지 않으므로 전체로 한 번 돌린다. 호출은 스레드
    수와 무관하게 pull 당 1 회다.

    git diff 는 untracked 파일을 보지 않으므로, rename 이 최소한 스테이지되어
    있어야 추적된다. 스테이지되지 않은 rename 은 D 로 보여 stale 이 된다.
    """
    result = PathMap()
    for line in gitcmd.diff_name_status(root, head_sha).splitlines():
        parts = line.split("\t")
        status = parts[0]
        if status.startswith("R") and len(parts) == 3:
            result.renames[parts[1]] = parts[2]
        elif status.startswith("D") and len(parts) == 2:
            result.deleted.add(parts[1])
    return result


class LineMap:
    """head_sha 의 줄 번호 → 작업 트리의 줄 번호."""

    def __init__(self, hunks: list[tuple[int, int, int, int]]) -> None:
        self.hunks = hunks

    def map(self, old_line: int) -> int | None:
        """삭제·수정 영역 안의 줄은 None (fallback 으로 넘긴다)."""
        delta = 0
        for old_start, old_count, _new_start, new_count in self.hunks:
            if old_count == 0:
                # `@@ -10,0 +11,3 @@` 는 old 10 번 줄 **뒤에** 삽입한다는 뜻이다.
                # 10 번 줄 자체는 움직이지 않는다.
                if old_line > old_start:
                    delta += new_count
            elif old_start <= old_line < old_start + old_count:
                return None
            elif old_line >= old_start + old_count:
                delta += new_count - old_count
        return old_line + delta


def line_map(
    root: Path, head_sha: str, head_path: str, current_path: str | None = None
) -> LineMap | None:
    """작업 트리와 비교한다. 커밋하지 않은 수정까지 반영된다.

    `head_path` 는 `head_sha` 시점의 경로, `current_path` 는 작업 트리의 경로다.
    rename 된 파일은 둘이 다르며, 존재 확인은 `head_path` 로 해야 한다 —
    작업 트리의 이름은 `head_sha` 에 없으므로 항상 False 가 된다.

    `head_sha` 에 경로가 없으면 None. `git diff -- <없는 경로>` 는 변경 없는
    경로와 똑같이 빈 출력을 내므로, 이 확인이 없으면 존재하지 않는 파일에
    "변경 없음"(항등 매핑)을 돌려주게 된다.
    """
    if not gitcmd.has_path(root, head_sha, head_path):
        return None
    paths = [p for p in dict.fromkeys([head_path, current_path]) if p]
    out = gitcmd.diff_u0(root, head_sha, *paths)
    if out is None:
        return None
    hunks = [
        (
            int(match[1]),
            int(match[2]) if match[2] is not None else 1,
            int(match[3]),
            int(match[4]) if match[4] is not None else 1,
        )
        for match in _HUNK.finditer(out)
    ]
    return LineMap(hunks)
