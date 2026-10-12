"""`mrq reanchor`. docs/spec/cli.md §6. 네트워크를 쓰지 않는다."""

from __future__ import annotations

import json
import sys

from mrq import model, reanchor, store, surface


def run(args) -> int:
    # 쓰기 명령이므로 브랜치가 어긋나면 멈춘다(cli.md §2). 재계산이 가능하다는
    # 것은 위로가 되지 않는다 — 다른 브랜치의 작업 트리로 계산한 location 과
    # confidence 가 그럴듯한 틀린 줄로 json 에 남고 md 에 렌더되며, 그것을
    # 덮어쓸 다음 pull 을 강제하는 장치가 없다. 에디터가 키 한 번으로 부르는
    # 경로라(editor.md §3.2) 경고는 읽히지 않는다.
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        review = model.loads(path.read_text(encoding="utf-8"))
        # 네트워크를 쓰지 않기로 한 명령이므로 커밋이 없으면 fetch 하지 않고
        # 문자열 탐색으로 degrade 한다.
        have_git = reanchor.ensure_commits(
            root, iid, review.source_branch, review.diff_refs, allow_fetch=False
        )
        stats = reanchor.reanchor_all(root, review, have_git=have_git)
        # cli.md §1 — reanchor 의 쓰기 대상은 json + md 재렌더다.
        surface.write(root, review, include_resolved=False)

    if args.json:
        # --json 일 때 stdout 은 순수 JSON 하나다.
        json.dump({"anchors": stats.as_dict()}, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
    else:
        print(f"reanchored: {stats}")
    return 0
