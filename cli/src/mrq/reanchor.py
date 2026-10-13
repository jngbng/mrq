"""재앵커링 오케스트레이션. docs/spec/reanchoring.md §5.

입력: position(서버 좌표), anchor(head_sha 내용), 현재 작업 트리.
출력: location(작업 트리 좌표).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from mrq import anchor, gitcmd, linemap, model, search

MR_HEAD_REFSPEC = "refs/merge-requests/{iid}/head"


@dataclass
class Stats:
    exact: int = 0
    fuzzy: int = 0
    stale: int = 0

    def count(self, confidence: str) -> None:
        setattr(self, confidence, getattr(self, confidence) + 1)

    def as_dict(self) -> dict[str, int]:
        return {"exact": self.exact, "fuzzy": self.fuzzy, "stale": self.stale}

    def __str__(self) -> str:
        return f"exact {self.exact} · fuzzy {self.fuzzy} · stale {self.stale}"


def ensure_commits(
    root: Path,
    iid: int,
    source_branch: str,
    diff_refs: model.DiffRefs,
    *,
    allow_fetch: bool = True,
) -> bool:
    """재앵커링에 필요한 커밋을 로컬에 확보한다.

    `head_sha` 가 없으면 git 매핑과 anchor 추출이 모두 불가능하므로 False 를
    돌려 문자열 탐색 전용 모드로 degrade 한다. `start_sha` 만 없으면 hunk 와
    old-side 코멘트를 잃지만 나머지는 동작한다.

    `allow_fetch=False` 면 fetch 를 시도하지 않는다. `reanchor` 는 네트워크를
    쓰지 않기로 되어 있고(docs/spec/cli.md §6), 에디터가 자주 호출하는 경로라
    오프라인에서 TCP 타임아웃만큼 멈추면 안 된다.
    """
    wanted = (diff_refs.head_sha, diff_refs.start_sha)
    if all(gitcmd.have_commit(root, sha) for sha in wanted):
        return True
    if allow_fetch:
        for refspec in (MR_HEAD_REFSPEC.format(iid=iid), source_branch):
            gitcmd.fetch(root, refspec)
            if all(gitcmd.have_commit(root, sha) for sha in wanted):
                return True
    return gitcmd.have_commit(root, diff_refs.head_sha)


@dataclass
class _Context:
    root: Path
    head_sha: str
    paths: linemap.PathMap
    have_git: bool
    _maps: dict[tuple[str, str], linemap.LineMap | None] = field(default_factory=dict)
    _trees: dict[str, list[str] | None] = field(default_factory=dict)

    def line_map(self, head_path: str, current_path: str) -> linemap.LineMap | None:
        key = (head_path, current_path)
        if key not in self._maps:
            self._maps[key] = (
                linemap.line_map(self.root, self.head_sha, head_path, current_path)
                if self.have_git
                else None
            )
        return self._maps[key]

    def worktree(self, path: str) -> list[str] | None:
        if path not in self._trees:
            self._trees[path] = _read_worktree(self.root / path)
        return self._trees[path]


def _read_worktree(path: Path) -> list[str] | None:
    try:
        raw = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    lines = raw.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def reanchor_all(root: Path, review: model.Review, *, have_git: bool = True) -> Stats:
    """`review.threads[*].location` 을 제자리에서 채우고 통계를 돌려준다."""
    stats = Stats()
    paths = linemap.path_map(root, review.diff_refs.head_sha) if have_git else linemap.PathMap()
    context = _Context(root, review.diff_refs.head_sha, paths, have_git)

    for thread in review.threads:
        position = thread.position
        if position is None or position.position_type != "text":
            # 위치가 애초에 없다. "찾지 못함"과 구분하며 통계에서도 제외한다.
            thread.location = None
            continue
        thread.location = _locate(context, thread)
        if thread.server.missing:
            # 서버 응답에서 사라졌지만 미전송 작업이 있어 보존한 스레드다
            # (data-model.md §4.10). 위치는 계속 채운다 — 사용자가 답글을 옮길
            # 곳을 찾는 데 쓰인다. 하지만 통계가 재는 것은 "현재 서버가 돌려준
            # 활성 코멘트를 얼마나 잘 재배치했는가"이고 이 스레드는 그 모집단이
            # 아니므로 섞으면 품질 게이트(reanchoring.md §8)가 조용히 낮아진다.
            continue
        stats.count(thread.location.confidence)
    return stats


def _locate(context: _Context, thread: model.Thread) -> model.Location:
    position = thread.position
    assert position is not None
    source_path = position.new_path or position.old_path
    stale = model.Location(
        path=source_path, line=None, line_end=None, confidence="stale", method="none"
    )

    if thread.anchor is None or not source_path:
        return stale

    current_path = context.paths.resolve(source_path)
    if current_path is None:
        return stale  # 삭제된 파일

    lines = context.worktree(current_path)
    if lines is None:
        return stale

    # 범위가 있으면 시작 줄은 position 이 아니라 line_range.start 다 — position
    # 쪽 값은 범위의 어느 쪽이든 될 수 있다 (anchor.start_line 의 주석).
    head_start = anchor.start_line(position)
    if position.new_line is not None:
        found = _locate_new_side(context, thread, source_path, current_path, lines, head_start)
    else:
        found = _locate_old_side(thread, lines, head_start)

    if found is None:
        return stale

    line, confidence, method = found
    line_end = None
    end_head_line = _range_end(position)
    if end_head_line is not None:
        line_end = _locate_range_end(
            context, source_path, current_path, lines, head_start, end_head_line, line
        )
        # start 와 end 는 서로 다른 메커니즘(git 매핑 vs 문자열 탐색)으로
        # 구해지므로 순서가 보장되지 않는다. 역전된 end 는 "찾지 못함"과
        # 같은 경로로 떨어뜨린다.
        if line_end is not None and line_end < line:
            line_end = None
        if line_end is None:
            # 한쪽만 찾았으면 start 만 쓰고 fuzzy 로 강등한다.
            confidence = "fuzzy"

    return model.Location(
        path=current_path,
        line=line,
        line_end=line_end,
        confidence=confidence,
        method=method,
    )


def _locate_new_side(
    context: _Context,
    thread: model.Thread,
    head_path: str,
    current_path: str,
    lines: list[str],
    head_line: int,
) -> tuple[int, str, str] | None:
    assert thread.anchor is not None

    mapped = None
    line_map = context.line_map(head_path, current_path)
    if line_map is not None:
        mapped = line_map.map(head_line)

    # 매핑 결과는 반드시 내용 검증을 거친다.
    if mapped is not None and 1 <= mapped <= len(lines):
        if lines[mapped - 1] == thread.anchor.line:
            return mapped, "exact", "git-diff"

    found = search.find(lines, thread.anchor, mapped or head_line)
    if found is None:
        return None
    return found[0], found[1], "anchor-search"


def _locate_old_side(
    thread: model.Thread, lines: list[str], old_line: int | None
) -> tuple[int, str, str] | None:
    """삭제된 줄. context_before 의 마지막 줄을 찾아 그 아래에 붙인다."""
    assert thread.anchor is not None
    if not thread.anchor.context_before:
        return None
    probe = model.Anchor(
        line=thread.anchor.context_before[-1],
        context_before=thread.anchor.context_before[:-1],
        context_after=[],
        hunk=None,
    )
    # position.old_line 을 탐색 창의 추정 위치로 넘긴다. None 을 넘기면 창이
    # 줄 0 을 중심으로 고정돼 ±50 밖의 context 줄은 전체 유일성 탐색에만
    # 의존하게 되고, 평범한 살아남은 context 줄은 유일하지 않아 stale 이 된다
    # (reanchoring.md §5.2 의 창은 "매핑 추정 위치"를 쓰라고 명시한다).
    found = search.find(lines, probe, old_line)
    if found is None:
        return None
    return min(found[0] + 1, len(lines)), "fuzzy", "context-anchor"


def _locate_range_end(
    context: _Context,
    head_path: str,
    current_path: str,
    lines: list[str],
    start_head_line: int | None,
    end_head_line: int,
    start_line: int,
) -> int | None:
    """멀티라인의 끝 줄.

    `anchor` 는 시작 줄의 내용만 담고 있으므로 끝 줄은 내용 검증으로 찾을 수
    없다. 라인 맵이 있으면 그것을 쓰고, 없으면 span 길이를 보존한다.
    """
    line_map = context.line_map(head_path, current_path)
    if line_map is not None:
        mapped = line_map.map(end_head_line)
        if mapped is not None and 1 <= mapped <= len(lines):
            return mapped
    if start_head_line is None:
        return None
    candidate = start_line + (end_head_line - start_head_line)
    return candidate if 1 <= candidate <= len(lines) else None


def _range_end(position: model.Position) -> int | None:
    """범위의 끝 줄. 코멘트가 붙은 쪽의 끝점만 쓴다.

    범위가 old/new 양쪽에 걸쳐 있으면 그 쪽 끝점이 비어 있다. 그때는 None 을
    돌려 §5.4 의 강등 규칙(`line_end: null` + `fuzzy`)으로 떨어뜨린다 —
    반대쪽 좌표계의 줄 번호를 끝으로 쓰면 그럴듯한 틀린 범위가 된다.
    """
    end = (position.line_range or {}).get("end") or {}
    return end.get("new_line") if position.new_line is not None else end.get("old_line")
