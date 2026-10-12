"""`mrq pull`. docs/spec/cli.md §4."""

from __future__ import annotations

import datetime as dt
import sys

from mrq import SCHEMA_VERSION, anchor, discussions, model, mr, reanchor, store


def _now() -> str:
    return dt.datetime.now().astimezone().isoformat(timespec="seconds")


def run(args) -> int:
    if args.render:
        print("렌더러는 아직 구현되지 않았습니다 (계획 2).", file=sys.stderr)
        return 1

    root = store.open_review(require_state=False).root

    info = mr.detect(root, args.mr)
    project, can_resolve = mr.project_info()
    user_id, username = mr.whoami()
    diff_refs = mr.diff_refs(info.iid)
    draft_notes = mr.draft_notes_available(info.iid)
    threads = discussions.to_threads(discussions.fetch(info.iid), username)

    with store.review_lock(root, info.iid):
        previous = _previous_state(root, info.iid)
        have_git = reanchor.ensure_commits(root, info.iid, info.source_branch, diff_refs)
        if not have_git:
            print(
                f"⚠ head_sha {diff_refs.head_sha[:7]} 를 가져올 수 없습니다. "
                "git 매핑을 쓸 수 없어 이전에 추출한 anchor 를 남아 있는 대로 "
                "재사용합니다. 정확도를 되찾으려면 pull 을 성공시켜야 합니다.",
                file=sys.stderr,
            )

        for thread in threads:
            extracted = anchor.extract(root, diff_refs, thread.position)
            if thread.id in previous:
                previous_local, previous_anchor = previous[thread.id]
                thread.local = previous_local
                if extracted is None and previous_anchor is not None:
                    # head_sha 를 확보하지 못해 git show 가 전부 실패한 경우.
                    # None 으로 덮어쓰면 이전에 뽑아둔 좋은 anchor 가 사라지고
                    # 모든 코멘트가 stale 이 되어 다시는 복구할 길이 없어진다.
                    thread.anchor = previous_anchor
                else:
                    thread.anchor = extracted
            else:
                thread.anchor = extracted

        review = model.Review(
            schema_version=SCHEMA_VERSION,
            project=project,
            iid=info.iid,
            title=info.title,
            web_url=info.web_url,
            mr_state=info.mr_state,
            source_branch=info.source_branch,
            diff_refs=diff_refs,
            me=model.Me(id=user_id, username=username, can_resolve=can_resolve),
            capabilities=model.Capabilities(draft_notes=draft_notes),
            pulled_at=_now(),
            rendered_at=None,
            threads=threads,
        )
        stats = reanchor.reanchor_all(root, review, have_git=have_git)
        store.atomic_write_text(store.review_json_path(root, info.iid), model.dumps(review))
        store.write_current(root, info.iid)

    unresolved = sum(1 for t in threads if not t.server.resolved)
    print(f"!{info.iid} {info.title} · threads {len(threads)} · unresolved {unresolved}")
    print(f"reanchored: {stats}   (head {diff_refs.head_sha[:7]})")
    return 0


def _previous_state(root, iid: int) -> dict[str, tuple[model.Local, model.Anchor | None]]:
    """기존 local.* 와 anchor 를 보존한다.

    local.* 를 덮어쓰면 전송하지 않은 답글이 사라진다. anchor 는 head_sha 를
    확보하지 못해 이번 pull 에서 추출에 실패했을 때 되돌릴 값으로 쓴다 — 그냥
    None 으로 덮으면 git 매핑도 anchor-search 도 할 거리가 없어져 재앵커링이
    전부 stale 이 되고 reanchor 로도 복구할 수 없다.
    """
    path = store.review_json_path(root, iid)
    if not path.is_file():
        return {}
    previous = model.loads(path.read_text(encoding="utf-8"))
    return {thread.id: (thread.local, thread.anchor) for thread in previous.threads}
