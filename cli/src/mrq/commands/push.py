"""`mrq push`. docs/spec/cli.md §9.

스레드마다 결과를 즉시 json 에 쓴다(MUST) — 중간에 죽어도 재실행으로 복구되어야
한다. 중복 전송 방지는 `pushed_hash` 와 서버 스냅샷의 동일 본문 두 겹이고,
`push.plan` 이 그 판정을 들고 있다.
"""

from __future__ import annotations

import argparse
import json
import sys

from mrq import discussions, mdsync, model, push, store, surface, transport
from mrq.commands import pull as pull_command
from mrq.errors import GlabError, MrqError, UsageError


def run(args) -> int:
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    with store.review_lock(root, iid):
        outcome = mdsync.perform(root, iid, path)
        if outcome.errors:
            return mdsync.report_errors(outcome.errors, json_mode=args.json)
        if outcome.conflicts:
            return mdsync.report_conflicts(iid, outcome.conflicts, json_mode=args.json)
        review = outcome.review
        for warning in outcome.warnings:
            print(f"review.md:{warning.line}: {warning.message}", file=sys.stderr)

        if args.resolve == "require" and not review.me.can_resolve:
            raise UsageError(
                "resolve 권한이 없습니다 (--resolve require). 아무것도 전송하지 않았습니다. "
                "`--resolve auto` 로 답글만 보낼 수 있습니다."
            )

        # 전체를 한 번만 조회한다(MUST). 스레드별 GET 은 N+1 이다.
        snapshot = discussions.to_threads(discussions.fetch(iid), review.me.username)
        sheet = push.plan(review, snapshot=snapshot, resolve=args.resolve, force=args.force)
        failures = _send(root, review, sheet)

    _repull(iid)
    return _report(sheet, failures, json_mode=args.json)


def _send(root, review: model.Review, sheet: push.Plan) -> list[dict]:
    by_id = {t.id: t for t in review.threads}
    failures: list[dict] = []
    for decision in sheet.targets():
        thread = by_id[decision.thread]
        if decision.record_hash:
            _mark_sent(thread, decision.record_hash)
        if decision.reply:
            try:
                transport.post_reply(review.iid, thread.id, decision.reply)
            except GlabError as exc:
                failures.append(_record_failure(thread, "reply", exc))
            else:
                _mark_sent(thread, push.body_hash(decision.reply))
        if decision.resolve:
            try:
                transport.resolve(review.iid, thread.id)
            except GlabError as exc:
                failures.append(_record_failure(thread, "resolve", exc))
                if exc.status == 403:
                    # 사전 판정이 틀릴 수 있다(커스텀 역할, 그룹 상속 권한, MR
                    # 잠금). 강등하면 다음 push 에서 이 스레드는 애초에 resolve
                    # 대상이 아니므로 재시도 루프가 상태 기계 차원에서 닫힌다.
                    thread.local.state = "replied"
            else:
                thread.server.resolved = True
                thread.local.push_error = None
        # 스레드 하나가 끝날 때마다 json 을 flush 한다(MUST). md 는 그리지
        # 않는다 — 재pull 이 한 번 그린다 (data-model.md §5.2 가 거짓 충돌이
        # 생기지 않는 이유다).
        store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
    return failures


def _mark_sent(thread: model.Thread, digest: str) -> None:
    thread.local.pushed_hash = digest
    thread.local.reply = ""
    thread.local.push_error = None
    thread.local.touched_by = "push"
    thread.local.touched_at = surface.now()


def _record_failure(thread: model.Thread, op: str, exc: GlabError) -> dict:
    thread.local.push_error = {
        "op": op,
        "status": exc.status,
        "reason": exc.reason,
        "retryable": exc.retryable,
        "at": surface.now(),
        "message": str(exc),
    }
    return {
        "thread": thread.id,
        "op": op,
        "status": exc.status,
        "reason": exc.reason,
        "retryable": exc.retryable,
    }


def _repull(iid: int) -> None:
    """서버 스냅샷을 다시 받고 md 를 한 번 그린다 (§9 5단계).

    락 밖에서 부른다 — `pull` 이 자기 락을 잡는다. 실패해도 종료 코드는 전송
    결과를 따른다(MUST): 전송 결과는 이미 json 에 있고, 그것을 네트워크 실패로
    덮으면 사용자가 "안 갔다" 로 읽는다.
    """
    namespace = argparse.Namespace(mr=iid, all=False, render=False, no_render=False)
    try:
        pull_command.run(namespace)
    except MrqError as exc:
        print(
            f"⚠ 전송 후 재pull 이 실패했습니다 ({exc}). 전송 결과는 review.json 에 "
            "기록되어 있습니다 — `mrq pull` 을 다시 실행하세요.",
            file=sys.stderr,
        )


def _report(sheet: push.Plan, failures: list[dict], *, json_mode: bool) -> int:
    sent_replies = sheet.replies - sum(1 for f in failures if f["op"] == "reply")
    sent_resolves = sheet.resolves - sum(1 for f in failures if f["op"] == "resolve")
    if json_mode:
        json.dump(
            {
                "pushed": {"replies": sent_replies, "resolves": sent_resolves},
                "failures": failures,
            },
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        print(f"pushed: 답글 {sent_replies}건 · resolve {sent_resolves}건")
        for failure in failures:
            retry = "재실행하면 다시 시도합니다" if failure["retryable"] else "재시도하지 않습니다"
            print(
                f"✗ {failure['thread'][:8]} {failure['op']} 실패 "
                f"({failure['reason']}, status {failure['status']}) — {retry}",
                file=sys.stderr,
            )
    return 4 if failures else 0
