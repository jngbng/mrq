"""`review.md` → 블록·경고·에러. 파일을 만지지 않는다.

docs/spec/review-md.md §6·§7. 이 파서는 AI 가 생성한 임의의 마크다운을 입력으로
받아도 깨지지 않아야 한다 — 표, 중첩 코드 펜스, 수평선, 앵커 문법의 인용이 모두
평범하게 들어온다. 절대 예외를 올리지 않는다; 에러를 종료 코드로 바꾸는 것은
`commands/sync.py` 다.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

from mrq import render

ANCHOR_RE = re.compile(r"^<!-- mrq:([0-9a-f]{8,})(?: v:([0-9a-f]{6}))? -->$")
_FILE_RE = re.compile(r"^<!-- mrq:file\s+(.*?)\s*-->$")
_HEADER_RE = re.compile(r"^## \[(.)\]")
# 여는 펜스는 관대하게 받는다 — ```python 처럼 정보 문자열이 붙는 것이 보통이다.
_FENCE_OPEN_RE = re.compile(r"^(?: {0,3})(`{3,}|~{3,})")
# 닫는 펜스는 CommonMark 와 같이 엄격하게 받는다 — 마커 뒤에 공백만 허용한다.
# 안 그러면 인용된 ```python 같은 내부 줄이 펜스를 조기에 닫아버린다.
_FENCE_CLOSE_RE = re.compile(r"^ {0,3}(`{3,}|~{3,})[ \t]*$")
_REPLY_RE = re.compile(r"^### reply$")
# 앵커 형식과 "거의" 같지만 ANCHOR_RE 에 걸리지 않는 줄 — id/v 가 손상된 경우.
# mrq:file·mrq:help 는 parse() 에서 먼저 소비되므로 여기 닿지 않는다.
_SUSPECT_RE = re.compile(r"^<!-- mrq:(\S.*?)\s*-->$")
# 손상된 앵커로 보려면 `mrq:` 뒤가 id 처럼 보이거나 `v:` 를 담고 있어야 한다.
# 그러지 않으면 답글에 평범히 쓴 `<!-- mrq:TODO 참고 -->` 같은 산문이 exit 2 가
# 되어 **다른 모든 스레드의 편집까지** 반영되지 못한다.
_ID_LIKE_RE = re.compile(r"^[0-9a-fA-F]{4,}")

_STATE_OF_CHAR = {" ": "todo", "x": "done", "~": "replied", "-": "skipped"}


@dataclass
class FileMeta:
    schema: int | None = None
    iid: int | None = None
    head: str | None = None
    rendered: str | None = None


@dataclass
class Block:
    thread_id: str
    v: str | None
    line: int
    state: str | None = None
    reply: str | None = None


@dataclass
class Message:
    line: int
    message: str


@dataclass
class SkippedAnchor:
    """fence 안에 있어 블록으로 등록하지 **않은** 앵커 줄 (§6 규칙 1).

    인용된 앵커(§6 규칙 1 이 명시적으로 허용하는 경우)와 "답글이 열어 둔 펜스가
    다음 스레드의 앵커를 삼킨 경우"가 파서 입장에서는 똑같이 보인다. 둘을 가르는
    유일한 신호는 그 id 가 `review.json` 에 있는지인데 그것은 파서가 모른다 —
    그래서 사실만 기록하고 판정은 `commands/sync.py` 가 한다.
    """

    thread_id: str
    line: int


@dataclass
class Parsed:
    meta: FileMeta = field(default_factory=FileMeta)
    blocks: list[Block] = field(default_factory=list)
    warnings: list[Message] = field(default_factory=list)
    errors: list[Message] = field(default_factory=list)
    skipped_anchors: list[SkippedAnchor] = field(default_factory=list)


def parse(text: str) -> Parsed:
    """줄 단위로 훑되 fenced code block 안에서는 앵커를 인식하지 않는다 (§6 규칙 1).

    CRLF 를 먼저 통일한다(MUST) — 에디터가 CRLF 로 저장하면 `\\r` 가 reply 끝에
    남아 `v` 해시가 전부 달라지고 모든 스레드가 "편집됨" 이 된다.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    parsed = Parsed()
    starts: list[tuple[int, str, str | None]] = []  # (index, thread_id, v)
    outside: set[int] = set()  # fence 바깥 줄의 index
    fence: str | None = None
    fence_start: int | None = None  # 열린 펜스의 index — 안 닫히면 여기로 에러를 낸다
    seen_file_comment = False  # 첫 번째 mrq:file 주석만 메타로 쓴다 (리플레이 인용 방지)

    for index, line in enumerate(lines):
        if fence is not None:
            closer = _FENCE_CLOSE_RE.match(line)
            if closer and closer.group(1)[0] == fence[0] and len(closer.group(1)) >= len(fence):
                fence = None
                fence_start = None
            elif anchor := ANCHOR_RE.match(line):
                # 규칙 1 대로 블록을 시작시키지 않되, 어떤 id 를 건너뛰었는지는
                # 남긴다. 답글이 펜스를 열어 둔 채 끝나면 **다음 스레드의**
                # ```diff 블록 닫는 줄이 그 펜스를 닫으므로, 그 사이의 앵커와
                # 헤더가 통째로 삼켜진다 — 파일 끝까지 안 닫히는 경우가 아니라서
                # 아래의 미닫힘 검사로는 잡히지 않는다.
                parsed.skipped_anchors.append(SkippedAnchor(anchor.group(1), index + 1))
            continue
        marker = _FENCE_OPEN_RE.match(line)
        if marker:
            fence = marker.group(1)
            fence_start = index
            continue
        outside.add(index)
        if meta := _FILE_RE.match(line):
            if not seen_file_comment:
                parsed.meta = _parse_meta(meta.group(1))
                seen_file_comment = True
            continue
        if line.startswith("<!-- mrq:help"):
            continue
        if anchor := ANCHOR_RE.match(line):
            starts.append((index, anchor.group(1), anchor.group(2)))
        elif (suspect := _SUSPECT_RE.match(line)) and _looks_damaged(suspect.group(1)):
            parsed.errors.append(
                Message(index + 1, f"앵커 주석 형식이 올바르지 않습니다 (§6 규칙 2): {line}")
            )

    if not seen_file_comment:
        # `cli.md` §5 는 `iid` 검증을 MUST 로 둔다. 주석이 없으면 iid 도 schema 도
        # 검사할 수 없으므로 "검사를 건너뛴다" 가 아니라 에러여야 한다 — AI 가
        # 헤더를 다시 쓴 md 를 엉뚱한 MR 에 sync 하면 답글이 다른 스레드로 간다.
        parsed.errors.append(
            Message(
                1,
                "`<!-- mrq:file ... -->` 주석이 없습니다 — 어느 MR 의 review.md 인지 "
                "확인할 수 없습니다. `mrq pull --render` 로 복원하세요",
            )
        )

    if fence is not None and fence_start is not None:
        parsed.errors.append(
            Message(
                fence_start + 1,
                "코드 펜스가 파일 끝까지 닫히지 않았습니다 — 블록 경계를 확정할 수 없습니다",
            )
        )

    seen: dict[str, int] = {}
    for position, (index, thread_id, v) in enumerate(starts):
        end = starts[position + 1][0] if position + 1 < len(starts) else len(lines)
        if thread_id in seen:
            parsed.errors.append(
                Message(
                    index + 1, f"앵커 ID {thread_id} 가 {seen[thread_id]} 행에서 이미 나왔습니다"
                )
            )
            continue
        seen[thread_id] = index + 1
        block = Block(thread_id=thread_id, v=v, line=index + 1)
        if v is None:
            parsed.warnings.append(
                Message(index + 1, f"{thread_id}: v: 토큰이 없어 편집된 것으로 간주합니다")
            )
        _fill_state(block, lines, index, end, outside, parsed)
        _fill_reply(block, lines, index, end, outside, parsed)
        parsed.blocks.append(block)
    return parsed


def _looks_damaged(body: str) -> bool:
    """`mrq:` 뒤의 본문이 "망가진 앵커" 로 볼 만한가.

    id 처럼 보이거나(hex 4자 이상으로 시작) `v:` 를 담고 있을 때만 참이다.
    `<!-- mrq:TODO 참고 -->` 같은 산문을 에러로 올리면 그 한 줄 때문에 다른
    모든 스레드의 편집이 반영되지 못한다 (§7 의 "부분 적용 금지" 가 이쪽으로
    작동하면 손해가 더 크다).
    """
    return bool(_ID_LIKE_RE.match(body)) or "v:" in body


def _parse_meta(body: str) -> FileMeta:
    # _FILE_RE 의 캡처 그룹은 이미 `mrq:file\s+` 뒤부터 시작하므로 "file" 접두어를
    # 다시 걸러낼 필요가 없다.
    values = dict(part.split("=", 1) for part in body.split() if "=" in part)
    return FileMeta(
        schema=_as_int(values.get("schema")),
        iid=_as_int(values.get("iid")),
        head=values.get("head"),
        rendered=values.get("rendered"),
    )


def _as_int(value: str | None) -> int | None:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None


def _fill_state(
    block: Block, lines: list[str], index: int, end: int, outside: set[int], parsed: Parsed
) -> None:
    """체크박스 = 앵커 **바로 다음 줄** 의 `^## \\[(.)\\]` (§6 규칙 4)."""
    header = lines[index + 1] if index + 1 < end and index + 1 in outside else ""
    match = _HEADER_RE.match(header)
    if match is None:
        # 앵커가 파일의 마지막 줄이면 index + 2 는 EOF 너머다 — compilation
        # 버퍼가 점프할 수 있도록 실제 마지막 줄로 자른다 (§7 MUST).
        parsed.warnings.append(
            Message(
                min(index + 2, len(lines)),
                f"{block.thread_id}: 앵커 다음 줄이 헤더가 아님 — 상태를 유지합니다",
            )
        )
        return
    char = match.group(1)
    if char not in _STATE_OF_CHAR:
        parsed.errors.append(
            Message(
                index + 2, f"체크박스 문자 '{char}' 를 해석할 수 없음 (허용: ' ', 'x', '~', '-')"
            )
        )
        return
    block.state = _STATE_OF_CHAR[char]


def _fill_reply(
    block: Block, lines: list[str], index: int, end: int, outside: set[int], parsed: Parsed
) -> None:
    """reply = 블록 안 **첫** `### reply` 다음 줄부터 블록 끝까지 (§6 규칙 5).

    fence 안의 `### reply` 는 시작점이 아니다 — AI 가 사용법을 인용하면 본문이
    그 줄 아래로 잘린다.
    """
    for cursor in range(index + 1, end):
        if cursor in outside and _REPLY_RE.match(lines[cursor]):
            block.reply = render.normalize_reply("\n".join(lines[cursor + 1 : end]))
            return
    parsed.warnings.append(
        Message(index + 1, f"{block.thread_id}: `### reply` 가 없음 — 답글을 유지합니다")
    )
