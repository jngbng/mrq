"""`review.md` → `review.json` 반영의 핵심. docs/spec/cli.md §5.

`sync` 와 `push` 가 같은 코드를 쓴다. `push` 는 **자기 락 안에서** 이것을
불러야 한다(MUST) — 락을 두 번 잡으면 그 틈에 에디터의 `sync` 가 끼어들어
검토면에서 본 것과 다른 것을 보낸다. 그래서 여기서는 락을 잡지 않는다.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

from mrq import SCHEMA_VERSION, conflict, mdparse, model, reanchor, store, surface, threads
from mrq.errors import SchemaVersionError, UsageError


@dataclass
class Outcome:
    review: model.Review | None = None
    applied: list[conflict.Applied] = field(default_factory=list)
    warnings: list[mdparse.Message] = field(default_factory=list)
    errors: list[mdparse.Message] = field(default_factory=list)
    conflicts: list[conflict.Conflict] = field(default_factory=list)
    stats: reanchor.Stats | None = None


def perform(
    root: Path,
    iid: int,
    path: Path,
    *,
    prefer: str | None = None,
    only_refs: tuple[str, ...] = (),
) -> Outcome:
    """md 를 json 에 반영하고 재앵커링한다. 호출자가 락을 잡고 있어야 한다.

    에러·충돌이면 **아무것도 쓰지 않고** 그 사실만 담아 돌려준다. 보고와 종료
    코드는 호출자(`sync` 또는 `push`)의 몫이다.
    """
    md_path = store.review_md_path(root, iid)
    if not md_path.is_file():
        raise UsageError(
            "review.md 가 없습니다. `mrq pull --render` 로 복원하세요. "
            "(review.json 은 온전합니다 — 답글과 상태는 그대로 있습니다)"
        )

    review = model.loads(path.read_text(encoding="utf-8"))
    parsed = mdparse.parse(md_path.read_text(encoding="utf-8"))

    if parsed.meta.schema is not None and parsed.meta.schema != SCHEMA_VERSION:
        raise SchemaVersionError(
            f"review.md 의 schema 가 {parsed.meta.schema} 입니다 (이 mrq 는 {SCHEMA_VERSION})."
        )
    if parsed.meta.iid is not None and parsed.meta.iid != iid:
        raise UsageError(
            f"다른 MR 의 review.md 입니다 (파일 iid {parsed.meta.iid}, 대상 {iid}). "
            "아무것도 쓰지 않았습니다."
        )
    if parsed.meta.head and parsed.meta.head != review.diff_refs.head_sha:
        print(
            f"⚠ review.md 의 head 가 {parsed.meta.head[:7]} 이고 현재 head 는 "
            f"{review.diff_refs.head_sha[:7]} 입니다. 재앵커링이 처리합니다.",
            file=sys.stderr,
        )

    errors = sorted(parsed.errors + _swallowed_anchor_errors(review, parsed), key=lambda m: m.line)
    if errors:
        return Outcome(errors=errors)

    only_ids = tuple(threads.resolve_ref(review, ref).id for ref in only_refs)
    applied, conflicts, extra = conflict.plan_sync(review, parsed, prefer=prefer, only=only_ids)
    if conflicts:
        return Outcome(conflicts=conflicts)

    at = surface.now()
    by_id = {t.id: t for t in review.threads}
    for item in applied:
        local = by_id[item.thread].local
        local.state = item.state
        local.reply = item.reply
        local.touched_by = "md"
        local.touched_at = at

    have_git = reanchor.ensure_commits(
        root, iid, review.source_branch, review.diff_refs, allow_fetch=False
    )
    stats = reanchor.reanchor_all(root, review, have_git=have_git)
    surface.write(root, review, include_resolved=False)
    return Outcome(
        review=review,
        applied=applied,
        warnings=parsed.warnings + extra,
        stats=stats,
    )


def _swallowed_anchor_errors(review, parsed: mdparse.Parsed) -> list[mdparse.Message]:
    """닫히지 않은 펜스가 `review.json` 의 스레드 앵커를 삼킨 경우 (review-md.md §7).

    펜스 안의 앵커를 블록으로 보지 않는 것은 §6 규칙 1 의 요구다 — AI 가 앵커
    문법을 인용하는 일이 실제로 있고, 그 인용은 `review.json` 에 **없는** id 를
    쓴다. 반면 삼켜진 id 가 json 에 있으면서 이 파싱에 블록이 하나도 없다면 그
    스레드의 편집이 조용히 사라진 것이다 — `[x]` 체크가 버려지고, 앞 스레드의
    `local.reply` 가 삼킨 마크업을 그대로 흡수해 `push` 가 깨진 본문을 보낸다.
    두 경우를 가르는 신호는 이 json 멤버십뿐이므로 판정이 여기(sync)에 있다.
    """
    known = {t.id for t in review.threads}
    in_md = {block.thread_id for block in parsed.blocks}
    out: list[mdparse.Message] = []
    seen: set[str] = set()
    for skipped in parsed.skipped_anchors:
        lost = skipped.thread_id in known and skipped.thread_id not in in_md
        if lost and skipped.thread_id not in seen:
            seen.add(skipped.thread_id)
            out.append(
                mdparse.Message(
                    skipped.line,
                    f"{skipped.thread_id}: 이 스레드의 앵커가 닫히지 않은 코드 펜스 안에 "
                    "들어가 블록이 사라졌습니다 — 바로 위 답글의 코드 펜스를 닫으세요",
                )
            )
    return out


def report_errors(errors: list[mdparse.Message], *, json_mode: bool) -> int:
    """exit 2 — 아무것도 쓰지 않았다. 줄 번호와 함께 보고한다(MUST).

    경고와 같은 규칙을 쓴다 — `--json` 이어도 stderr 로 함께 보낸다. 사람이
    터미널에서 `--json` 을 돌렸을 때 아무 메시지도 못 보는 경로를 없앤다
    (`cli.md` §2 는 stdout 이 순수 JSON 이기만 요구한다).
    """
    for error in errors:
        print(f"review.md:{error.line}: {error.message}", file=sys.stderr)
    print("파싱 에러가 있어 아무것도 쓰지 않았습니다.", file=sys.stderr)
    if json_mode:
        json.dump(
            {"errors": [{"line": e.line, "message": e.message} for e in errors]},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    return 2


def report_conflicts(iid: int, conflicts: list[conflict.Conflict], *, json_mode: bool) -> int:
    """exit 3 — 아무것도 쓰지 않았다. md 쪽 값과 json 쪽 값을 함께 보고한다(MUST)."""
    if json_mode:
        json.dump(
            {"iid": iid, "conflicts": [c.as_dict() for c in conflicts]},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        for item in conflicts:
            print(f"충돌 {item.thread}", file=sys.stderr)
            print(f"  md   [{item.md_state}] {item.md_reply!r}", file=sys.stderr)
            print(f"  json [{item.json_state}] {item.json_reply!r}", file=sys.stderr)
        print(
            "`mrq sync --prefer md|json [--thread ID]` 로 해소하세요. 아무것도 쓰지 않았습니다.",
            file=sys.stderr,
        )
    return 3
