"""`mrq clean`. docs/spec/cli.md §11."""

from __future__ import annotations

import shutil
import sys

from mrq import glab, model, prompt, store
from mrq.errors import MrqError
from mrq.mr import PROJECT


def run(args) -> int:
    root = store.repo_root()
    # 모든 명령의 시작에서 보장한다 (data-model.md §1 MUST). `doctor` 만
    # 예외다 — 진단이 상태를 만들면 "없음" 을 진단할 수 없다.
    store.ensure_mrq_gitignore(root)
    wanted = _wanted(args)
    current = store.read_current(root)
    targets = []

    for directory in sorted(store.mrq_dir(root).glob("*/review.json")):
        # `current` 는 `<iid>/` 를 가리키는 심링크라 glob 이 같은 파일을
        # `current/review.json` 으로도 내놓는다. 숫자가 아닌 이름은 그
        # 별명이므로 건너뛴다 — 안 걸러내면 int() 가 터지거나 같은 MR 을
        # 두 번 처리한다.
        name = directory.parent.name
        if not name.isdigit():
            continue
        iid = int(name)
        try:
            data = glab.api(f"{PROJECT}/merge_requests/{iid}")
        except MrqError as exc:
            print(f"⚠ !{iid} 의 상태를 확인할 수 없습니다 ({exc}) — 건너뜁니다.", file=sys.stderr)
            continue
        state = (data or {}).get("state")
        if state not in wanted:
            continue
        targets.append((iid, state, _unsent(root, iid)))

    if not targets:
        print("제거할 것이 없습니다.")
        return 0

    for iid, state, unsent in targets:
        suffix = f" — 미전송 작업 {unsent}건" if unsent else ""
        print(f"!{iid} ({state}){suffix}")
    if args.dry_run:
        return 0

    pending = sum(unsent for _, _, unsent in targets)
    if pending:
        prompt.confirm(
            f"미전송 작업이 {pending}건 남아 있습니다. 제거하면 답글을 복구할 수 없습니다.",
            force=args.force,
        )

    for iid, _, _ in targets:
        shutil.rmtree(store.review_dir(root, iid))
        if iid == current:
            # 끊어진 심링크를 남기지 않는다(MUST).
            store.clear_current(root)
    print(f"removed: {len(targets)}개")
    return 0


def _wanted(args) -> set[str]:
    """플래그가 없으면 merged 와 closed 둘 다 (§11)."""
    if not args.merged and not args.closed:
        return {"merged", "closed"}
    return {name for name, on in (("merged", args.merged), ("closed", args.closed)) if on}


def _unsent(root, iid: int) -> int:
    """전송하지 않은 작업이 있는 스레드 수. 손상 json 은 0 으로 둔다."""
    path = store.review_json_path(root, iid)
    try:
        review = model.loads(path.read_text(encoding="utf-8"))
    except MrqError:
        return 0
    return sum(
        1 for thread in review.threads if thread.local.reply.strip() or thread.local.state != "todo"
    )
