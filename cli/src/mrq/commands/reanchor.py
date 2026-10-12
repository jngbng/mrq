"""`mrq reanchor`. docs/spec/cli.md §6. 네트워크를 쓰지 않는다."""

from __future__ import annotations

import json
import sys

from mrq import model, reanchor, store


def run(args) -> int:
    context = store.open_review()
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        review = model.loads(path.read_text(encoding="utf-8"))
        # 네트워크를 쓰지 않기로 한 명령이므로 커밋이 없으면 fetch 하지 않고
        # 문자열 탐색으로 degrade 한다.
        have_git = reanchor.ensure_commits(
            root, iid, review.source_branch, review.diff_refs, allow_fetch=False
        )
        stats = reanchor.reanchor_all(root, review, have_git=have_git)
        store.atomic_write_text(path, model.dumps(review))

    if args.json:
        # --json 일 때 stdout 은 순수 JSON 하나다.
        json.dump({"anchors": stats.as_dict()}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(f"reanchored: {stats}")
    return 0
