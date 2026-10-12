"""`mrq list`. docs/spec/cli.md §7. AI 에이전트의 읽기 경로다."""

from __future__ import annotations

import json
import sys
from dataclasses import asdict

from mrq import model, render, store
from mrq import threads as thread_select


def run(args) -> int:
    context = store.open_review(on_branch_change="warn")
    review = model.loads(context.path.read_text(encoding="utf-8"))
    selected = render.order(
        thread_select.filter_threads(
            review.threads,
            state=args.state,
            confidence=args.confidence,
            include_resolved=args.all,
        )
    )

    if args.json:
        json.dump(
            {
                "iid": review.iid,
                "schema_version": review.schema_version,
                "threads": [asdict(t) for t in selected],
            },
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0

    for thread in selected:
        print(_line(thread))
    return 0


def _line(thread: model.Thread) -> str:
    header = render.header_line(thread)
    # `## [x] src/a.py:7 — @jdoe  `fuzzy`` 에서 상태·위치·작성자·배지를 재사용한다.
    body = header.removeprefix("## ")
    first = ""
    if thread.notes:
        first = next((line for line in thread.notes[0].body.splitlines() if line.strip()), "")
    excerpt = first if len(first) <= 40 else first[:39] + "…"
    return f"{thread.id[:8]}  {body}   {excerpt}"
