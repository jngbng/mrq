"""`mrq state`. docs/spec/cli.md §10."""

from __future__ import annotations

from mrq import model, store, surface
from mrq import threads as thread_select


def run(args) -> int:
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        review = model.loads(path.read_text(encoding="utf-8"))
        thread = thread_select.resolve_ref(review, args.thread)
        thread.local.state = args.state
        thread.local.touched_by = "cli"
        thread.local.touched_at = surface.now()
        surface.write(root, review, include_resolved=False)

    print(f"{thread.id[:8]} [{args.state}]")
    return 0
