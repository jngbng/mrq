"""`review.json` → `review.md` 문자열. 파일을 만지지 않는다.

docs/spec/review-md.md §1~5. `v:` 해시의 정규형 정의가 이 모듈에만 있어야
한다 — 렌더와 파싱이 다른 정규형을 쓰면 사람이 손대지 않은 파일을 sync 해도
전부 "편집됨" 으로 잡힌다 (data-model.md §5.1).
"""

from __future__ import annotations

import datetime as dt
import hashlib
from pathlib import Path

from mrq import model

_STATE_CHAR = {"todo": " ", "done": "x", "replied": "~", "skipped": "-"}


def normalize_reply(text: str) -> str:
    """렌더링된 정규형. 줄 끝을 `\\n` 으로 통일하고 앞뒤 빈 줄만 제거한다.

    내부는 바이트 보존이다 (review-md.md §6) — 코드 블록 안의 공백을 건드리면
    답글 내용이 망가진다.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    while lines and not lines[0].strip():
        lines.pop(0)
    while lines and not lines[-1].strip():
        lines.pop()
    return "\n".join(lines)


def vhash(state: str, reply: str) -> str:
    """`sha256(state + "\\n" + normalized_reply)` 의 앞 6 자 (data-model.md §5.1).

    6 자(24비트)를 쓰는 이유는 충돌 시 "사람이 편집했는데 안 했다고 판정" 해서
    답글이 조용히 사라지는 것이 가장 나쁜 실패 양상이기 때문이다.
    """
    payload = f"{state}\n{normalize_reply(reply)}".encode()
    return hashlib.sha256(payload).hexdigest()[:6]


def visible(threads: list[model.Thread], *, include_resolved: bool) -> list[model.Thread]:
    """렌더 대상 스레드 (review-md.md §5).

    서버에서 resolve 된 것은 기본적으로 감추지만, **전송하지 않은 답글이 있으면**
    `--all` 없이도 보여야 한다(MUST) — 동료가 내 스레드를 먼저 resolve 했을 때
    내 답글이 md 에서 사라지고 사용자는 잃은 줄도 모른다.

    "전송 안 됨" 의 신호는 `local.reply` 하나다. `push` 가 성공해야 그것을
    비우기 때문이다(`cli.md` §9). `local.state` 로는 가를 수 없다 — 보낸 뒤에도
    `done`/`replied` 로 남으므로, 그것까지 보여 주면 **끝난 스레드가 영영
    목록에 남아** 남은 작업에 집중할 수 없다.

    서버가 이미 resolve 했으므로 `state == "done"` 이 요청하던 resolve 도 이미
    이뤄졌다 — 그 쪽으로도 보낼 것이 없다.
    """
    out = []
    for thread in threads:
        if include_resolved or not thread.server.resolved:
            out.append(thread)
        elif thread.local.reply.strip():
            out.append(thread)
    return out


def order(threads: list[model.Thread]) -> list[model.Thread]:
    """`location` 없는 스레드 먼저(created_at 순), 그 다음 (path, line) 순 (MUST).

    id 로 마지막 tie-break 를 둔다. 같은 줄에 코멘트가 둘일 때 입력 순서에
    따라 결과가 흔들리면 재렌더마다 diff 가 생긴다.
    """
    general = [t for t in threads if _path_of(t) is None]
    located = [t for t in threads if _path_of(t) is not None]
    general.sort(key=lambda t: (t.notes[0].created_at if t.notes else "", t.id))
    located.sort(key=lambda t: (_path_of(t) or "", _line_of(t), t.id))
    return general + located


def where(thread: model.Thread) -> str:
    """위치 표시의 기본 형태 — `(general)` 또는 `<path>:<line>`.

    `header_line`(review.md 헤더)과 `commands/push._where`(`--dry-run` 위치
    칼럼)가 **같은 규칙**을 쓰기 위해 공유한다(Minor 7) — 전자는
    `line or 1`, 후자는 `max(line, 1)`을 따로 써 이미 두 번 드리프트했다.
    신뢰도·`server-missing` 배지는 두 호출자가 각자 다르게 붙인다(아래
    `header_line` 참고) — 하나는 `no-reply`까지 더 붙이고, 다른 하나는
    `--dry-run` 행에 이미 skip 이유로 나오는 `no-reply`를 중복으로
    붙이지 않는다.
    """
    path = _path_of(thread)
    if path is None:
        return "(general)"
    return f"{path}:{_line_of(thread)}"


def header_line(thread: model.Thread) -> str:
    """`## [<상태>] <path>:<line> — @<author>  [배지...]` (review-md.md §3)."""
    author = thread.notes[0].author if thread.notes else "?"
    badges: list[str] = []
    # 신뢰도 배지는 위치가 있는(path 가 있는) 스레드에만 붙인다 — `(general)`
    # 스레드는 `_path_of`가 `None`을 돌려주므로 여기 닿지 않는다. `where()`가
    # 이미 그 분기로 "(general)"을 돌려주지만, 배지는 `where()`가 감추는
    # 정보(원본 `location`)를 다시 봐야 해서 따로 판정한다.
    if _path_of(thread) is not None and thread.location.confidence in ("stale", "fuzzy"):
        badges.append(f"`{thread.location.confidence}`")
    if not thread.server.repliable:
        badges.append("`no-reply`")
    if thread.server.missing:
        badges.append("`server-missing`")
    suffix = "  " + " ".join(badges) if badges else ""
    return f"## [{_STATE_CHAR[thread.local.state]}] {where(thread)} — @{author}{suffix}"


def _path_of(thread: model.Thread) -> str | None:
    if thread.location is None:
        return None
    return thread.location.path or None


def _line_of(thread: model.Thread) -> int:
    """stale 은 line 이 None 이다. 헤더에서는 1 행으로 쓴다 (진단은 만들지 않는다)."""
    if thread.location is None or thread.location.line is None:
        return 1
    return max(thread.location.line, 1)


_HELP = """<!-- mrq:help
  체크박스: [ ] 미처리 · [x] 완료(resolve) · [~] 답글만 · [-] 건너뜀
  답글은 각 스레드의 `### reply` 아래에 씁니다. 표·코드블록·--- 모두 자유롭게 쓸 수 있습니다.
  `<!-- mrq:... -->` 줄은 지우거나 수정하지 마세요. 그 외의 모든 내용은 무시됩니다.
  다 쓴 뒤 `mrq sync`, 확인은 `mrq status`, 전송은 `mrq push`.
-->"""


def _quotes(thread: model.Thread) -> list[str]:
    """`> **@author** YYYY-MM-DD HH:MM` 다음 줄부터 본문. 노트 사이에 `>` 한 줄.

    본문의 **모든** 줄에 접두사를 붙인다(MUST). 빈 줄은 `>` 단독이다 — 접두사를
    빼면 인용이 끊기고, GitLab 코멘트에는 빈 줄을 포함한 코드 블록이 흔하다.
    """
    if not thread.notes:
        return []
    out: list[str] = []
    for index, note in enumerate(thread.notes):
        if index:
            out.append(">")
        out.append(f"> **@{note.author}** {stamp(note.created_at)}")
        for raw in note.body.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
            out.append(f"> {raw}" if raw.strip() else ">")
    out.append("")
    return out


def stamp(value: str, pattern: str = "%Y-%m-%d %H:%M") -> str:
    """시각을 로컬 타임존으로 변환해 포맷한다 (docs/spec/review-md.md §5).

    GitLab 은 `created_at` 을 UTC 로 준다. 기록된 오프셋 그대로 출력하면
    08:07 에 단 코멘트가 전날 23:07 로 보이는데, 같은 화면의 `pulled`/`synced`
    는 우리가 만든 로컬 시각이라 9시간 어긋난 두 시각이 섞인다.

    타임존 정보가 없는 값은 추측하지 않고 그대로 포맷한다. 골든 테스트의
    결정성은 TZ 고정으로 확보한다 (`docs/spec/testing.md` §2).
    """
    try:
        parsed = dt.datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return value or "-"
    if parsed.tzinfo is not None:
        parsed = parsed.astimezone()
    return parsed.strftime(pattern)


_LANGUAGE = {
    ".py": "python",
    ".ts": "typescript",
    ".tsx": "tsx",
    ".js": "javascript",
    ".jsx": "jsx",
    ".el": "elisp",
    ".md": "markdown",
    ".json": "json",
    ".sh": "bash",
    ".bash": "bash",
    ".yml": "yaml",
    ".yaml": "yaml",
    ".go": "go",
    ".rs": "rust",
    ".c": "c",
    ".h": "c",
    ".cc": "cpp",
    ".cpp": "cpp",
    ".hpp": "cpp",
    ".java": "java",
    ".kt": "kotlin",
    ".rb": "ruby",
    ".sql": "sql",
    ".toml": "toml",
    ".css": "css",
    ".scss": "scss",
    ".html": "html",
    ".xml": "xml",
}


def _fence(body: list[str]) -> str:
    """본문보다 긴 울타리를 고른다.

    context 가 마크다운 파일에서 왔거나 hunk 가 코드 펜스를 담고 있으면 3 백틱이
    문서를 깨뜨린다. 파서는 fence 를 추적하므로(§6 규칙 1) 길이가 맞아야 한다.
    """
    longest = 0
    for line in body:
        stripped = line.lstrip()
        if stripped.startswith("`"):
            longest = max(longest, len(stripped) - len(stripped.lstrip("`")))
    return "`" * max(3, longest + 1)


def _code_block(thread: model.Thread) -> list[str]:
    """`anchor.hunk` 가 있으면 diff 펜스, 없으면 파일 언어 펜스 (review-md.md §4)."""
    anchor = thread.anchor
    if anchor is None:
        return []
    if anchor.hunk:
        body = anchor.hunk.replace("\r\n", "\n").rstrip("\n").split("\n")
        fence = _fence(body)
        return [f"{fence}diff", *body, fence, ""]
    body = [*anchor.context_before, anchor.line, *anchor.context_after]
    fence = _fence(body)
    language = _LANGUAGE.get(Path(_source_path(thread) or "").suffix, "")
    return [f"{fence}{language}", *body, fence, ""]


def _source_path(thread: model.Thread) -> str | None:
    if thread.location is not None and thread.location.path:
        return thread.location.path
    if thread.position is not None:
        return thread.position.new_path or thread.position.old_path
    return None


def _summary_line(review: model.Review) -> str:
    unresolved = sum(1 for t in review.threads if not t.server.resolved)
    stats = {"exact": 0, "fuzzy": 0, "stale": 0}
    for thread in review.threads:
        # location: null 은 재앵커링 통계에서 제외한다 (data-model.md §4.9 MUST).
        if thread.location is not None and thread.location.confidence in stats:
            stats[thread.location.confidence] += 1
    return (
        f"head {review.diff_refs.head_sha[:7]} · pulled {stamp(review.pulled_at, '%H:%M')} · "
        f"unresolved {unresolved} · "
        f"exact {stats['exact']} fuzzy {stats['fuzzy']} stale {stats['stale']}"
    )


def _thread_block(thread: model.Thread) -> list[str]:
    lines = [
        f"<!-- mrq:{thread.id} v:{vhash(thread.local.state, thread.local.reply)} -->",
        header_line(thread),
        "",
    ]
    lines.extend(_code_block(thread))
    lines.extend(_quotes(thread))
    lines.append("### reply")
    lines.append("")  # 고정: `### reply` 뒤 빈 줄 하나 (MUST)
    body = normalize_reply(thread.local.reply)
    if body:
        lines.append(body)
    lines.append("")  # 고정: 다음 앵커 전 빈 줄 하나 (MUST)
    return lines


def render(review: model.Review, *, include_resolved: bool = False) -> str:
    """`review.json` → `review.md` 전체 문자열 (review-md.md §1).

    `head` 는 full sha 로 적는다. `sync` 가 `diff_refs.head_sha` 와 문자열 비교로
    대조하므로(cli.md §5) 축약하면 매번 경고가 난다.
    """
    out = [
        # `rendered=<시각>` 을 넣지 않는다.  읽는 코드가 하나도 없었는데
        # (진짜 `rendered_at` 은 `review.json` 에 있다) 매 렌더마다 1 행이
        # 달라져, `sync` 가 아무것도 바꾸지 않아도 파일이 변했다.  에디터는
        # 그때마다 버퍼를 되읽고 화면이 흔들린다 (`editor.md` §3.3).
        f"<!-- mrq:file schema={review.schema_version} iid={review.iid} "
        f"head={review.diff_refs.head_sha} -->",
        _HELP,
        "",
        f"# !{review.iid} {review.title}",
        "",
        _summary_line(review),
        "",
    ]
    for thread in order(visible(review.threads, include_resolved=include_resolved)):
        out.extend(_thread_block(thread))
    while out and out[-1] == "":
        out.pop()
    return "\n".join(out) + "\n"
