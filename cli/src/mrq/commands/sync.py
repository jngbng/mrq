"""`mrq sync`. docs/spec/cli.md §5. 네트워크를 쓰지 않는다."""

from __future__ import annotations

import json
import sys

from mrq import mdsync, store


def run(args) -> int:
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        outcome = mdsync.perform(
            root,
            iid,
            path,
            prefer=args.prefer,
            only_refs=tuple(args.thread or ()),
        )
    if outcome.errors:
        return mdsync.report_errors(outcome.errors, json_mode=args.json)
    if outcome.conflicts:
        return mdsync.report_conflicts(iid, outcome.conflicts, json_mode=args.json)

    # 경고는 --json 여부와 무관하게 stderr 로도 보낸다(`cli.md` §2 MUST) —
    # stdout 은 순수 JSON 이어야 하므로 --json 일 때도 페이로드에만 담으면
    # 사람이 터미널에서 그냥 보는 경로가 없어진다.
    for warning in outcome.warnings:
        print(f"review.md:{warning.line}: {warning.message}", file=sys.stderr)

    if args.json:
        json.dump(
            {
                "iid": iid,
                "applied": [item.as_dict() for item in outcome.applied],
                "warnings": [{"line": w.line, "message": w.message} for w in outcome.warnings],
                "anchors": outcome.stats.as_dict(),
            },
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        changed = sum(1 for item in outcome.applied if item.reply_changed)
        print(
            f"synced: {len(outcome.applied)} 스레드 반영 (답글 {changed}건) "
            f"· reanchored: {outcome.stats}"
        )
    return 0
