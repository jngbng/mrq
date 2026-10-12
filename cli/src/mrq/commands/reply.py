"""`mrq reply`. docs/spec/cli.md §10. VSCode CodeLens 와 AI 의 쓰기 경로다."""

from __future__ import annotations

import sys
from pathlib import Path

from mrq import model, render, store, surface
from mrq import threads as thread_select
from mrq.errors import UsageError


def run(args) -> int:
    body = _body(args)
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        review = model.loads(path.read_text(encoding="utf-8"))
        thread = thread_select.resolve_ref(review, args.thread)
        thread.local.reply = render.normalize_reply(body)
        if args.state:
            thread.local.state = args.state
        thread.local.touched_by = "cli"
        thread.local.touched_at = surface.now()
        # md 를 즉시 재렌더한다(MUST) — v: 해시가 함께 갱신되어 거짓 충돌을 막는다.
        surface.write(root, review, include_resolved=False)

    print(f"{thread.id[:8]} [{thread.local.state}] 답글 {len(thread.local.reply)}자 기록")
    return 0


def _body(args) -> str:
    """본문을 읽고 **비어 있으면 거부한다**.

    빈 본문을 그대로 기록하면 사람이 아직 보내지 않은 답글이 정본 json 에서
    사라진다 — 충돌도 경고도 없이, `-F -` 의 파이프가 빈 경우라는 흔한 배관
    실수만으로. 상태만 바꾸는 것은 `mrq state` 의 일이다.
    """
    body = _read(args)
    if not body.strip():
        raise UsageError(
            "답글 본문이 비어 있습니다. 아무것도 쓰지 않았습니다. "
            "상태만 바꾸려면 `mrq state <thread> <todo|done|replied|skipped>` 를 쓰세요."
        )
    return body


def _read(args) -> str:
    if args.message is not None:
        return args.message
    if args.file is None:
        raise UsageError("본문이 없습니다. `-m MSG` 또는 `-F FILE` / `-F -` 를 쓰세요.")
    if args.file == "-":
        return sys.stdin.read()
    source = Path(args.file)
    if not source.is_file():
        raise UsageError(f"{args.file} 을 읽을 수 없습니다.")
    return source.read_text(encoding="utf-8")
