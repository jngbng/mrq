"""`anchor` 추출. docs/spec/reanchoring.md §3.

anchor 는 head_sha 시점의 파일 내용에서 뽑는다. 작업 트리에서 읽으면 안 된다 —
이미 바뀌어 있다.
"""

from __future__ import annotations

import re
from pathlib import Path

from mrq import gitcmd, model

CONTEXT_LINES = 3

_HUNK_HEADER = re.compile(r"^@@ -(\d+)(?:,(\d+))? \+(\d+)(?:,(\d+))? @@")


def read_lines(root: Path, rev: str, path: str) -> list[str] | None:
    """`git show <rev>:<path>` 의 내용을 줄 리스트로 돌려준다.

    Python 의 text 모드가 이미 universal newlines 로 변환하므로 이 `replace` 는
    방어적 중복이다. 바이너리 모드로 바뀌어도 동작하도록 남겨둔다.
    UTF-8 로 디코딩할 수 없으면 None (호출자가 stale 로 처리한다).
    """
    raw = gitcmd.show(root, rev, path)
    if raw is None:
        return None
    try:
        raw.encode("utf-8")
    except UnicodeEncodeError:
        return None
    lines = raw.replace("\r\n", "\n").split("\n")
    if lines and lines[-1] == "":
        lines.pop()
    return lines


def extract(
    root: Path, diff_refs: model.DiffRefs, position: model.Position | None
) -> model.Anchor | None:
    if position is None or position.position_type != "text":
        return None

    if position.new_line is not None:
        rev, path, line_no = diff_refs.head_sha, position.new_path, position.new_line
    elif position.old_line is not None:
        # 삭제된 줄은 head_sha 에 없다. start_sha 에서 읽는다.
        rev, path, line_no = diff_refs.start_sha, position.old_path, position.old_line
    else:
        return None

    if not path:
        return None

    lines = read_lines(root, rev, path)
    if lines is None:
        return None
    if not 1 <= line_no <= len(lines):
        # GitLab 이 낡은 position 을 그대로 주는 경우가 있다. 예외를 전파해
        # pull 전체를 실패시키지 않는다.
        return None

    index = line_no - 1
    return model.Anchor(
        line=lines[index],
        # max(0, ...) 가 없으면 음수 인덱스가 빈 슬라이스를 만들어 context 를 잃는다.
        context_before=lines[max(0, index - CONTEXT_LINES) : index],
        context_after=lines[index + 1 : index + 1 + CONTEXT_LINES],
        hunk=hunk_for(root, diff_refs, position),
    )


def hunk_for(root: Path, diff_refs: model.DiffRefs, position: model.Position) -> str | None:
    """리뷰어가 본 diff 에서 대상 줄을 포함하는 hunk 하나를 떼어낸다.

    discussions 응답에는 hunk 가 없다. GitLab 의 diffs 엔드포인트를 쓰지 않고
    로컬 git 으로 구하면 호출이 늘지 않는다.
    """
    # 양쪽 경로를 모두 넘긴다. 하나만 넘기면 rename 된 파일에서 git 이
    # "새 파일 추가"로 보고해 hunk 에 파일 전체가 들어온다.
    paths = [p for p in dict.fromkeys([position.old_path, position.new_path]) if p]
    if not paths:
        return None
    out = gitcmd.diff_u3(root, diff_refs.start_sha, diff_refs.head_sha, *paths)
    if out is None:
        return None

    use_new = position.new_line is not None
    target = position.new_line if use_new else position.old_line
    if target is None:
        return None

    for old_start, old_count, new_start, new_count, text in _split_hunks(out):
        start, count = (new_start, new_count) if use_new else (old_start, old_count)
        if start <= target < start + max(count, 1):
            return text
    return None


def _split_hunks(diff_text: str) -> list[tuple[int, int, int, int, str]]:
    hunks: list[list] = []
    current: list | None = None
    for line in diff_text.splitlines(keepends=True):
        match = _HUNK_HEADER.match(line)
        if match:
            if current is not None:
                hunks.append(current)
            current = [
                int(match[1]),
                int(match[2]) if match[2] is not None else 1,
                int(match[3]),
                int(match[4]) if match[4] is not None else 1,
                line,
            ]
        elif current is not None:
            current[4] += line
    if current is not None:
        hunks.append(current)
    return [(h[0], h[1], h[2], h[3], h[4]) for h in hunks]
