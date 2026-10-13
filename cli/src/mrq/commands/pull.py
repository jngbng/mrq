"""`mrq pull`. docs/spec/cli.md §4."""

from __future__ import annotations

import sys

from mrq import SCHEMA_VERSION, anchor, discussions, model, mr, reanchor, store, surface


def run(args) -> int:
    if args.render:
        return _render_only(args)

    root = store.open_review(require_state=False).root

    info = mr.detect(root, args.mr)
    project, can_resolve = mr.project_info()
    user_id, username = mr.whoami()
    diff_refs = mr.diff_refs(info.iid)
    draft_notes = mr.draft_notes_available(info.iid)
    threads = discussions.to_threads(discussions.fetch(info.iid), username)

    with store.review_lock(root, info.iid):
        previous, previous_warnings = _previous(root, info.iid)
        for warning in previous_warnings:
            print(f"⚠ {warning}", file=sys.stderr)
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

        threads = _carry_missing(root, info.iid, threads)

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
            pulled_at=surface.now(),
            # 이전 값을 이어받는다. `--no-render` 면 md 는 디스크에 그대로
            # 남아 있는데 `rendered_at` 만 None 이 되어 `status` 가 `synced -`
            # 를 찍고 "md 가 없다" 처럼 보인다. 렌더하는 경우에는
            # `surface.write` 가 즉시 now() 로 덮으므로 영향이 없다.
            rendered_at=_previous_rendered_at(root, info.iid),
            threads=threads,
        )
        stats = reanchor.reanchor_all(root, review, have_git=have_git)
        surface.write(root, review, include_resolved=args.all, md=not args.no_render)
        store.write_current(root, info.iid)

    unresolved = sum(1 for t in threads if not t.server.resolved)
    print(f"!{info.iid} {info.title} · threads {len(threads)} · unresolved {unresolved}")
    print(f"reanchored: {stats}   (head {diff_refs.head_sha[:7]})")
    return 0


def _previous(
    root, iid: int
) -> tuple[dict[str, tuple[model.Local, model.Anchor | None]], list[str]]:
    """기존 local.* 와 anchor 를 보존한다 (data-model.md §6).

    local.* 를 덮어쓰면 전송하지 않은 답글이 사라진다. anchor 는 head_sha 를
    확보하지 못해 이번 pull 에서 추출에 실패했을 때 되돌릴 값으로 쓴다 — 그냥
    None 으로 덮으면 git 매핑도 anchor-search 도 할 거리가 없어져 재앵커링이
    전부 stale 이 되고 reanchor 로도 복구할 수 없다.
    """
    path = store.review_json_path(root, iid)
    if not path.is_file():
        return {}, []
    return model.read_previous(path.read_text(encoding="utf-8"))


def _previous_rendered_at(root, iid: int) -> str | None:
    """직전 `rendered_at`. 스키마 검증에 묶지 않는다 (`model.peek_*` 와 같은 이유)."""
    path = store.review_json_path(root, iid)
    if not path.is_file():
        return None
    return model.peek_rendered_at(path.read_text(encoding="utf-8"))


def _carry_missing(root, iid: int, threads: list[model.Thread]) -> list[model.Thread]:
    """응답에서 사라진 스레드 중 미전송 작업이 있는 것을 보존한다 (§4.10).

    미전송 작업이 없는 스레드는 그대로 제거한다 — 보존해서 표시할 로컬 상태가
    없으므로 남기면 md 와 `status` 에 설명할 수 없는 항목이 쌓인다.
    """
    path = store.review_json_path(root, iid)
    if not path.is_file():
        return threads
    present = {thread.id for thread in threads}
    carried = []
    for thread_id, previous in model.read_threads(path.read_text(encoding="utf-8")).items():
        if thread_id in present:
            continue
        if not (previous.local.reply.strip() or previous.local.state != "todo"):
            continue
        previous.server.missing = True
        carried.append(previous)
        print(
            f"⚠ {thread_id[:8]} 스레드가 서버 응답에서 사라졌습니다 — 미전송 작업이 "
            "있어 보존합니다. `push` 는 전송하지 않으므로 답글을 직접 옮기세요.",
            file=sys.stderr,
        )
    return threads + carried


def _render_only(args) -> int:
    """`--render` — md 만 다시 그린다. 네트워크를 쓰지 않는다 (cli.md §4).

    md 가 날아간 경우의 복구 경로다. `--all` 과 함께 쓰면 서버에서 resolve 된
    스레드까지 전부 볼 수 있다.
    """
    context = store.open_review()
    with store.review_lock(context.root, context.iid):
        review = model.loads(context.path.read_text(encoding="utf-8"))
        surface.write(context.root, review, include_resolved=args.all)
    print(f"rendered: {store.review_md_path(context.root, context.iid)}")
    return 0
