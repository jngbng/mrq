"""`mrq push`. docs/spec/cli.md §9.

스레드마다 결과를 즉시 json 에 쓴다(MUST) — 중간에 죽어도 재실행으로 복구되어야
한다. 중복 전송 방지는 `pushed_hash` 와 서버 스냅샷의 동일 본문 두 겹이고,
`push.plan` 이 그 판정을 들고 있다.
"""

from __future__ import annotations

import argparse
import contextlib
import json
import sys

from mrq import discussions, mdsync, model, prompt, push, store, surface, transport
from mrq.commands import pull as pull_command
from mrq.errors import GlabError, MrqError, UsageError


def run(args) -> int:
    context = store.open_review(on_branch_change="fail")
    root, iid, path = context.root, context.iid, context.path

    if args.resolve == "require" or args.draft:
        # 둘 다 "push 를 시작하지 않고 exit 1" 이다(§9) — sync·락보다 앞서
        # 끊어야 그 말이 글자 그대로 맞는다. `me.can_resolve` 와
        # `capabilities` 는 sync 가 건드리는 필드가 아니므로 디스크의 값을
        # 그대로 읽어도 된다.
        pre = model.loads(path.read_text(encoding="utf-8"))
        if args.resolve == "require" and not pre.me.can_resolve:
            raise UsageError(
                "resolve 권한이 없습니다 (--resolve require). 아무것도 전송하지 않았습니다. "
                "`--resolve auto` 로 답글만 보낼 수 있습니다."
            )
        if args.draft and not pre.capabilities.draft_notes:
            raise UsageError(
                "이 GitLab 은 draft_notes API 를 지원하지 않습니다 (--draft 를 쓸 수 "
                "없습니다). 일반 전송은 `mrq push` 입니다."
            )

    # `--publish` 단독은 sync·스냅샷 **둘 다** 생략한다(cli.md §9 `--draft`) —
    # 발행은 서버에 이미 있는 draft 를 내보내는 일이라 로컬 review.md 와
    # 무관하다. md 에 파싱 에러나 충돌이 있어도, 이미 사용자 손을 떠난 draft 를
    # 발행하지 못하게 막으면 안 된다.
    publish_only = args.publish and not args.draft

    with store.review_lock(root, iid):
        if publish_only:
            review = model.loads(path.read_text(encoding="utf-8"))
            sheet = push.plan(review, resolve=args.resolve, force=args.force)
        else:
            outcome = mdsync.perform(root, iid, path)
            if outcome.errors:
                return mdsync.report_errors(outcome.errors, json_mode=args.json)
            if outcome.conflicts:
                return mdsync.report_conflicts(iid, outcome.conflicts, json_mode=args.json)
            review = outcome.review
            for warning in outcome.warnings:
                print(f"review.md:{warning.line}: {warning.message}", file=sys.stderr)

            # 전체를 한 번만 조회한다(MUST). 스레드별 GET 은 N+1 이다.
            snapshot = discussions.to_threads(discussions.fetch(iid), review.me.username)
            sheet = push.plan(review, snapshot=snapshot, resolve=args.resolve, force=args.force)

        if args.dry_run:
            if publish_only:
                return _report_dry_run_publish(review, json_mode=args.json)
            return _report_dry_run(review, sheet, json_mode=args.json, draft_mode=args.draft)
        if review.mr_state != "opened":
            prompt.confirm(
                f"MR 이 {review.mr_state} 상태입니다. 보통은 브랜치를 바꾼 뒤 "
                "`.mrq/current` 가 낡은 것을 가리키고 있다는 신호입니다.",
                force=args.force,
            )
        draft_mode = bool(args.draft or args.publish)
        if draft_mode:
            failures, pushed = _run_draft(root, review, sheet, args, json_mode=args.json)
        else:
            failures, pushed = _send(root, review, sheet)

    # `publish_only` 는 md 를 다시 그리지 않는다(ruling 1) — sync 를 건너뛰었으니
    # md 에 아직 반영되지 않은 사용자의 수정이 있을 수 있다. 재pull 이 md 를
    # 덮어쓰면 그 수정이 흔적 없이 사라진다 — 결정 0012 가 막으려는 것과 같은
    # 손실이다. md 를 그대로 두면 다음 `sync`가 그 수정을 받아들인다.
    _repull(iid, json_mode=args.json, no_render=publish_only)
    return _report(sheet, failures, json_mode=args.json, pushed=pushed, draft_mode=draft_mode)


# `push.SKIP_REASONS` 와 같은 집합을 덮어야 한다. 빠진 값이 있으면 그 스레드의
# 행에서 KeyError 가 난다 — 검토면이 터지는 가장 싼 방법이다.
_SKIP_TEXT = {reason: reason for reason in push.SKIP_REASONS}


def _report_dry_run(
    review: model.Review, sheet: push.Plan, *, json_mode: bool, draft_mode: bool = False
) -> int:
    """`--dry-run`. `draft_mode`(=`--draft`)면 각 행을 draft 로 묶일 것으로
    표시한다 — 그대로 두면 "보냈다" 로 읽혀 draft 는 전송이 아니라는 결정
    0012 와 어긋난다. `--publish` 단독의 미리보기는 `_report_dry_run_publish`
    가 따로 맡는다(그 경로는 `sheet` 가 스냅샷 없이 만들어져 이 함수가 보여줄
    수 있는 것과 의미가 다르다).
    """
    if json_mode:
        payload = {
            "iid": review.iid,
            "push": {
                "replies": sheet.replies,
                "resolves": sheet.resolves,
                "skip": sheet.skip,
            },
            "decisions": [
                {
                    "thread": d.thread,
                    "reply": bool(d.reply),
                    "bytes": len(d.reply.encode()),
                    "resolve": d.resolve,
                    "skip": d.skip,
                }
                for d in sheet.decisions
            ],
            "warnings": sheet.warnings,
        }
        if draft_mode:
            payload["mode"] = "draft"
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    by_id = {t.id: t for t in review.threads}
    for decision in sheet.decisions:
        where = _where(by_id[decision.thread])
        # reply/resolve 는 액션 단위로 독립이다 (push.Decision 의 docstring) —
        # `decision.skip` 이 있다고 바로 "skip" 한 줄로 끝내면, 한쪽은 보내고
        # 다른 쪽만 막힌 경우(reply 는 가는데 resolve 만 no-resolve-permission
        # 으로 막히는 등)가 순수 skip 처럼 보인다. 검토면이 "아무 일도 없다"
        # 고 말하는데 다음 push 가 실제로 무언가를 보내면, 이 화면의 존재
        # 이유 자체가 무너진다. 그래서 ops 를 skip 과 무관하게 먼저 모으고,
        # skip 이유는 ops 가 있든 없든 그 옆에 덧붙인다.
        ops = []
        if decision.reply:
            ops.append(f"reply({len(decision.reply.encode())}B)")
        if decision.resolve:
            ops.append("resolve")
        if not ops and decision.record_hash:
            ops.append("기록만 (서버에 이미 있음)")
        if not ops:
            # 보낼 액션이 전혀 없다 — 순수 skip 한 줄.
            print(f"{decision.thread[:8]}  skip  {_SKIP_TEXT[decision.skip]:<16}  {where}")
            continue
        label = " + ".join(ops)
        if draft_mode:
            label = f"draft {label}"
        if decision.skip:
            # 한쪽은 보내지만 다른 쪽이 막혔다 — 그 사실을 같은 줄에 덧붙인다.
            label += f"  (skip {_SKIP_TEXT[decision.skip]})"
        print(f"{decision.thread[:8]}  {label:<24}  {where}")
    if not sheet.decisions:
        print("만들 draft 가 없습니다." if draft_mode else "보낼 것이 없습니다.")
    return 0


def _report_dry_run_publish(review: model.Review, *, json_mode: bool) -> int:
    """`--dry-run --publish` 단독. 실제로 발행될 draft 목록을 보여준다.

    `publish_only` 경로의 `sheet` 는 snapshot 없이 만들어져 `server-changed`
    를 보여줄 수 없다 — 그 사전 판정 자체가 의미 없다(발행은 서버의 draft 를
    그대로 내보내는 일이다). 그래서 `sheet` 대신 `GET draft_notes` 로 실제
    발행 대상을 조회해 보여준다. 조회만 하고 쓰지 않는다 — `--dry-run` 이다.
    """
    drafts = transport.list_drafts(review.iid)
    ours = [d for d in drafts if _ours(review, d)]
    foreign = [d for d in drafts if not _ours(review, d)]
    if json_mode:
        json.dump(
            {
                "iid": review.iid,
                "publish": {"drafts": len(drafts), "ours": len(ours), "foreign": len(foreign)},
                "decisions": [
                    {
                        "thread": d.get("discussion_id"),
                        "resolve": bool(d.get("resolve_discussion")),
                        "ours": _ours(review, d),
                    }
                    for d in drafts
                ],
            },
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
        return 0

    if not drafts:
        print("발행할 draft 가 없습니다.")
        return 0
    for draft in drafts:
        thread_id = draft.get("discussion_id")
        label = thread_id[:8] if thread_id else "(foreign)"
        tag = "" if _ours(review, draft) else "  (mrq 가 만들지 않음)"
        resolve_tag = " + resolve" if draft.get("resolve_discussion") else ""
        print(f"{label}  draft{resolve_tag}{tag}")
    if foreign:
        print(f"mrq 가 만들지 않은 draft {len(foreign)}건이 함께 발행됩니다.")
    return 0


def _where(thread: model.Thread) -> str:
    """`--dry-run` 의 위치 칼럼. `review.md` 헤더와 같은 규칙을 쓴다."""
    if thread.location is None or not thread.location.path:
        return "(general)"
    line = thread.location.line or 1
    suffix = (
        f"    `{thread.location.confidence}`"
        if thread.location.confidence in ("stale", "fuzzy")
        else ""
    )
    return f"{thread.location.path}:{line}{suffix}"


def _send(root, review: model.Review, sheet: push.Plan) -> tuple[list[dict], dict[str, int]]:
    """실제로 보낸다. 실패 목록과 함께 **실제로 나간** 건수도 돌려준다.

    Important 3 — `pushed.resolves`를 `sheet.resolves`(계획)에서 실패 건수를
    빼 재구성하면, reply POST 가 실패해 resolve 를 시도조차 하지 않은 경우에도
    계획에 잡혀 있던 수가 그대로 "보냈다"로 센다. 계획과 실제 전송은 서로
    다른 질문이다 — 여기서 직접 세어 그 간극을 없앤다.
    """
    by_id = {t.id: t for t in review.threads}
    failures: list[dict] = []
    sent_replies = 0
    sent_resolves = 0
    for decision in sheet.targets():
        thread = by_id[decision.thread]
        # 이번 스레드에서 reply POST 가 실패했는가. §9 의 4a·4b 는 한 스레드에
        # 대한 두 액션이다 — 답글이 올라가지 않았으면 그 스레드는 "done" 이
        # 아니므로 resolve 를 시도해서도, 방금 기록한 reply 실패를 성공한
        # resolve 가 지워서도 안 된다 (리뷰어는 "답글 없이 닫힌 스레드" 를
        # 보게 된다).
        failed_here = False
        if decision.record_hash:
            _mark_sent(thread, decision.record_hash)
        if decision.reply:
            try:
                transport.post_reply(review.iid, thread.id, decision.reply)
            except GlabError as exc:
                failures.append(_record_failure(thread, "reply", exc))
                failed_here = True
            else:
                _mark_sent(thread, push.body_hash(decision.reply))
                sent_replies += 1
        if decision.resolve and not failed_here:
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
                sent_resolves += 1
        # 스레드 하나가 끝날 때마다 json 을 flush 한다(MUST). md 는 그리지
        # 않는다 — 재pull 이 한 번 그린다 (data-model.md §5.2 가 거짓 충돌이
        # 생기지 않는 이유다).
        store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
    return failures, {"replies": sent_replies, "resolves": sent_resolves}


def _mark_sent(thread: model.Thread, digest: str, *, clear_reply: bool = True) -> None:
    """성공한 전송이 쓰는 필드 — `_send`(일반 전송)와 `_publish`(발행) 둘 다
    이 함수 하나를 거친다. "무엇을 쓰는가" 의 정의가 두 곳으로 갈라지면
    한쪽만 고치고 잊는 사고가 난다.

    `clear_reply=False` 는 결정 0012 전용이다 — 발행된 draft 본문이 현재
    `local.reply` 와 다르면(사용자가 draft 생성 뒤 md 에서 고쳤다) 비우지
    않는다. `pushed_hash` 는 그래도 **발행된 본문**의 해시로 기록해, 고친
    답글은 해시가 달라 다음 `push` 가 정상 전송하게 한다.
    """
    thread.local.pushed_hash = digest
    if clear_reply:
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


def _run_draft(
    root, review: model.Review, sheet: push.Plan, args, *, json_mode: bool
) -> tuple[list[dict], dict[str, int]]:
    """draft 생성과 발행. 결정 0012.

    중복 방어는 `GET draft_notes` 한 번이 전부다(MUST) — `pushed_hash` 가 아직
    없으므로 두 겹이 아니다. 조회가 실패하면 draft 를 만들지 않는다: 방어 없이
    만들면 재실행이 draft 를 복제하고, 복제된 draft 는 mrq 가 지울 수 없다.

    `pushed`(replies/resolves)는 **실제로 나간 것**만 센다 — draft 생성은
    전송이 아니므로 아무것도 만들지 않았을 때도 `{0, 0}`이다. `--publish`가
    같이 오면 발행된 draft 수로 덮어쓴다.
    """
    drafts = transport.list_drafts(review.iid)  # GlabError → exit 5
    failures: list[dict] = []
    pushed = {"replies": 0, "resolves": 0}
    if args.draft:
        failures += _create_drafts(root, review, sheet, drafts, json_mode=json_mode)
    if args.publish:
        if args.draft:
            # 방금 만든 draft 는 위 조회 결과에 없다 — 발행 뒤 pushed_hash
            # 기록·reply 정리가 그 스레드만 건너뛰지 않도록 다시 조회한다.
            drafts = transport.list_drafts(review.iid)
        published, publish_failures = _publish(
            root, review, drafts, force=args.force, json_mode=json_mode
        )
        failures += publish_failures
        pushed = published
    return failures, pushed


def _ours(review: model.Review, draft: dict) -> bool:
    """이 draft 가 review 의 스레드에 걸려 있는가 — `discussion_id` 로만 본다.

    body 비교는 여기 쓰지 않는다(ruling 2) — draft 를 만든 뒤 답글을 고쳐도
    여전히 우리 draft 다. body 비교는 `_publish`가 발행 시점에 `local.reply`
    를 비울지 정하는 데만 쓴다. `discussion_id`가 없는 draft(UI 에서 새로
    시작한 미완성 리뷰)는 항상 foreign 이다.
    """
    return draft.get("discussion_id") in {t.id for t in review.threads}


def _create_drafts(
    root, review: model.Review, sheet: push.Plan, drafts: list[dict], *, json_mode: bool
) -> list[dict]:
    """답글과 resolve 를 draft 하나로 묶는다. resolve 는 `resolve_discussion`
    에 실어 보내고 별도 `PUT discussions` 는 보내지 않는다(MUST NOT).

    `sheet.targets()`가 내놓는 `Decision`을 `_send`와 **같은 순서로** 읽는다
    (Critical 교정) — record_hash 먼저, 그다음 reply, 그 다음에야 resolve를
    같은 draft에 묶는다. 두 함수가 같은 Decision을 다르게 읽으면 한쪽에서
    고친 버그(2차 방어)가 다른 쪽(이 함수)에는 그대로 남는다.

    `decision.record_hash`는 2차 방어(스냅샷에 같은 본문의 내 note가 이미
    있음)가 걸렸다는 뜻이다 — 그 답글은 이미 **실제 note**로 서버에 있으므로
    draft로 묶을 것이 없다. `_send`처럼 해시만 기록한다(§9 MUST) — 기록하지
    않으면 다음 실행도 매번 스냅샷에 의존한다. `decision.reply`는 이 경우
    항상 비어 있다(`push.plan`이 둘을 같이 채우지 않는다) — 그래서
    `thread.local.reply`로 폴백하면(교정 전 버그) 이미 전송된 본문이 되살아나
    또 draft로 올라간다.

    `reply`가 없는데 `resolve`만 남은 경우(record_hash 뒤에 남은 resolve
    포함)는 Important 2와 같은 이유로 draft를 만들 수 없다 — `POST
    draft_notes`의 `note`는 필수라 빈 본문은 GitLab이 거부하거나(400),
    받아들이면 빈 note가 실제로 생긴다. §9가 별도 `PUT discussions`를
    금지하므로(MUST NOT) draft 경로로는 resolve만 표현할 수 없다. 건너뛰고
    이름을 대 일반 `push`를 안내한다 — 리뷰어가 추적을 잃지 않게.

    중복 방어 키는 `(discussion_id, body)` 다 — `resolve_discussion` 은 보지
    않는다. 그래서 답글 본문은 그대로인데 새로 resolve 가 필요해진 스레드는
    이미 있는 draft(resolve 없음)에 가로막혀 조용히 생략된다. draft 수정은
    범위 밖이므로(결정 0012) 고칠 수 없다 — 대신 이름을 대고 경고한다.
    """
    existing = {
        (d.get("discussion_id"), (d.get("note") or "").strip()): bool(d.get("resolve_discussion"))
        for d in drafts
    }
    by_id = {t.id: t for t in review.threads}
    failures: list[dict] = []
    attempted = 0
    created = 0
    for decision in sheet.targets():
        thread = by_id[decision.thread]

        if decision.record_hash:
            # 2차 방어 — 답글은 이미 실제 note 로 서버에 있다. `_send`와 같은
            # 방식으로 기록만 한다(Critical 교정).
            _mark_sent(thread, decision.record_hash)
            if decision.resolve:
                print(
                    f"⚠ {thread.id[:8]} 답글은 이미 서버에 있고 resolve 만 남았습니다 — "
                    "본문 없는 draft 는 만들 수 없습니다. `mrq push` 로 resolve 하세요.",
                    file=sys.stderr,
                )
            store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
            continue

        if not decision.reply:
            if decision.resolve:
                # Important 2 — resolve-only 스레드는 draft 로 표현할 수 없다.
                print(
                    f"⚠ {thread.id[:8]} resolve 만 있는 스레드는 draft 로 만들 수 없습니다 "
                    "(본문 없는 draft 는 보낼 수 없습니다) — `mrq push` 로 resolve 하세요.",
                    file=sys.stderr,
                )
            continue

        attempted += 1
        body = decision.reply
        key = (thread.id, body.strip())
        if key in existing:
            # 1단계의 중복 방어. 이미 같은 쌍의 draft 가 있다 — 조용히 생략한다.
            if decision.resolve and not existing[key]:
                print(
                    f"⚠ {thread.id[:8]} 이미 있는 draft 는 resolve 를 담고 있지 않습니다 — "
                    "GitLab UI 에서 지우고 다시 만드세요.",
                    file=sys.stderr,
                )
            continue
        try:
            transport.create_draft(review.iid, thread.id, body, resolve=decision.resolve)
        except GlabError as exc:
            failures.append(_record_failure(thread, "draft", exc))
        else:
            # 성공해도 local.reply 와 pushed_hash 는 건드리지 않는다(MUST NOT,
            # 결정 0012) — 발행 전까지는 사용자 글이 GitLab 의 내 draft 안에만
            # 있으므로 로컬에서 지우면 잃는다. 과거 실패가 남아 있었다면
            # 이번 성공으로 비운다(§9 가 모든 작업에 요구하는 일반 규칙).
            thread.local.push_error = None
            created += 1
            if not json_mode:
                # `--json` 에서는 stdout 이 `_report` 의 JSON 객체 하나여야
                # 한다(cli.md §2) — 사람용 줄은 그 모드에서 찍지 않는다.
                print(f"draft {thread.id[:8]}{' (+resolve)' if decision.resolve else ''}")
        # 스레드 하나가 끝날 때마다 json 을 flush 한다(MUST, §9 4c 와 같다).
        store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
    if not json_mode and created == 0 and not failures:
        if attempted == 0:
            print("만들 draft 가 없습니다.")
        else:
            # 대상은 있었지만 전부 1단계 중복 방어에 걸렸다 — "만들 게
            # 없다" 가 아니라 "이미 있다" 다. 서로 다른 신호다.
            print("이미 같은 draft 가 있습니다.")
    return failures


def _publish(
    root, review: model.Review, drafts: list[dict], *, force: bool, json_mode: bool
) -> tuple[dict[str, int], list[dict]]:
    """`bulk_publish` 는 내 pending draft **전부**를 발행한다 (선택적 발행이 없다)."""
    ours = [d for d in drafts if _ours(review, d)]
    foreign = [d for d in drafts if not _ours(review, d)]
    if foreign:
        prompt.confirm(
            f"mrq 가 만들지 않은 draft 가 {len(foreign)}건 있습니다. "
            "bulk_publish 는 내 draft 전부를 발행하므로 그것들도 함께 공개됩니다.",
            force=force,
        )
    if not drafts:
        if not json_mode:
            print("발행할 draft 가 없습니다.")
        return {"replies": 0, "resolves": 0}, []

    try:
        transport.bulk_publish(review.iid)
    except GlabError as exc:
        # 발행은 MR 전체 단위다(선택적 발행이 없다) — 실패를 스레드 하나에
        # 떠넘기지 않고, 이번에 발행하려던 내 draft 전부에 기록한다(ruling 3).
        # 발행되지 않았으니 replies/resolves 는 0 이다.
        failures = [
            _record_failure(
                next(t for t in review.threads if t.id == draft.get("discussion_id")),
                "publish",
                exc,
            )
            for draft in ours
        ]
        store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
        return {"replies": 0, "resolves": 0}, failures

    # 발행된 본문의 해시를 기록하고, **현재 값이 그 본문과 같을 때만** 비운다
    # (결정 0012) — draft 를 만든 뒤 md 에서 고친 답글을 지우면 그 수정이
    # 사라진다. "무엇을 쓰는가" 의 정의는 `_mark_sent` 하나뿐이다 — 여기서
    # 같은 필드를 다시 나열하면 두 정의가 갈라질 수 있다.
    for draft in drafts:
        thread = next((t for t in review.threads if t.id == draft.get("discussion_id")), None)
        if thread is None:
            continue
        note = draft.get("note") or ""
        _mark_sent(
            thread, push.body_hash(note), clear_reply=thread.local.reply.strip() == note.strip()
        )
    store.atomic_write_text(store.review_json_path(root, review.iid), model.dumps(review))
    if not json_mode:
        # 사람이 읽는 줄은 전체 수와 foreign 수를 **같이** 보여준다 — payload
        # 의 `pushed.replies`(= `len(ours)`)와 다른 수(= `len(drafts)`)를
        # 말없이 따로 찍으면 둘이 서로 다른 답을 하는 것처럼 보인다.
        print(f"published: {len(drafts)}건 (mrq 가 만들지 않은 {len(foreign)}건 포함)")
    # `pushed.replies`/`resolves`는 발행된 "우리" draft 수만 센다(ruling 4) —
    # bulk_publish 가 함께 내보낸 foreign draft 는 우리가 보낸 것이 아니다.
    pushed = {
        "replies": len(ours),
        "resolves": sum(1 for d in ours if d.get("resolve_discussion")),
    }
    return pushed, []


def _repull(iid: int, *, json_mode: bool, no_render: bool = False) -> None:
    """서버 스냅샷을 다시 받고 md 를 한 번 그린다 (§9 5단계).

    락 밖에서 부른다 — `pull` 이 자기 락을 잡는다. 실패해도 종료 코드는 전송
    결과를 따른다(MUST): 전송 결과는 이미 json 에 있고, 그것을 네트워크 실패로
    덮으면 사용자가 "안 갔다" 로 읽는다.

    `pull.run` 은 사람이 읽는 요약 두 줄을 stdout 에 찍는다 — `--json` 일 때
    그대로 두면 `push --json` 의 stdout 이 그 줄 + `_report` 의 JSON 객체,
    두 조각이 되어 `cli.md` §2 의 "stdout 은 순수 JSON 객체 하나" MUST 를
    깬다. `pull.run` 자신의 계약(사람 모드에서는 stdout 요약)은 바꾸지 않고,
    여기서만 그 출력을 stderr 로 돌린다 — 요약은 사라지지 않고 경로만 바뀐다.

    `no_render`(ruling 1)는 `--publish` 단독 뒤에만 켠다. 그 경로는 sync 를
    건너뛰므로 로컬 `review.md` 에 아직 반영되지 않은 사용자의 수정이 있을 수
    있다 — 재pull 이 md 를 덮어쓰면 그 수정이 흔적 없이 사라진다(결정 0012 가
    막으려는 것과 같은 손실). md 를 그대로 두면 다음 `sync`가 받아들인다.
    """
    namespace = argparse.Namespace(mr=iid, all=False, render=False, no_render=no_render)
    try:
        if json_mode:
            with contextlib.redirect_stdout(sys.stderr):
                pull_command.run(namespace)
        else:
            pull_command.run(namespace)
    except MrqError as exc:
        print(
            f"⚠ 전송 후 재pull 이 실패했습니다 ({exc}). 전송 결과는 review.json 에 "
            "기록되어 있습니다 — `mrq pull` 을 다시 실행하세요.",
            file=sys.stderr,
        )


def _report(
    sheet: push.Plan,
    failures: list[dict],
    *,
    json_mode: bool,
    pushed: dict[str, int],
    draft_mode: bool = False,
) -> int:
    """`pushed`는 항상 **실제로 나간** 건수다(Important 3) — 호출자(`_send`
    또는 `_run_draft`)가 직접 세어 넘긴다. 예전에는 일반 경로에서 `sheet`
    (계획)와 실패를 대조해 재구성했는데, reply POST 가 실패해 resolve 를
    시도조차 하지 않은 스레드도 계획에 잡힌 수만큼 "보냈다" 로 세어졌다 —
    계획과 실제 전송은 서로 다른 질문이라 한쪽에서 다른 쪽을 유도하면
    틀린다.

    `draft_mode`는 표시 문구만 가른다 — `--draft`/`--publish` 경로는
    `_create_drafts`/`_publish`가 이미 사람이 읽는 줄을 찍었으므로 여기서
    "pushed: 답글 N건"을 또 찍지 않는다(ruling 4, 중복 방지).
    """
    if json_mode:
        json.dump(
            {"pushed": pushed, "failures": failures},
            sys.stdout,
            ensure_ascii=False,
        )
        sys.stdout.write("\n")
    else:
        if not draft_mode:
            if not sheet.decisions:
                print("보낼 것이 없습니다.")
            else:
                print(f"pushed: 답글 {pushed['replies']}건 · resolve {pushed['resolves']}건")
        for failure in failures:
            retry = "재실행하면 다시 시도합니다" if failure["retryable"] else "재시도하지 않습니다"
            print(
                f"✗ {failure['thread'][:8]} {failure['op']} 실패 "
                f"({failure['reason']}, status {failure['status']}) — {retry}",
                file=sys.stderr,
            )
    return 4 if failures else 0
