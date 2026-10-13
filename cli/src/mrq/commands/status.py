"""`mrq status`. docs/spec/cli.md §8."""

from __future__ import annotations

import json
import sys

from mrq import model, push, render, report, store

# `server-changed` 는 없다 — `status` 는 네트워크를 쓰지 않으므로 그 질문에
# 정직하게 답할 수 없다 (`report.py` 의 모듈 docstring, `cli.md` §8).
_REASON_TEXT = {
    "no-reply": "개별 노트라 답글 전송 불가",
    "not-resolvable": "resolve 할 수 없는 스레드",
    "server-missing": "서버 응답에서 사라짐 — 전송하지 않습니다",
    "todo-with-reply": "답글이 있는데 상태가 [ ] — 전송되지 않습니다",
    "push-failed": "지난 전송이 실패했습니다 (review.json 의 push_error)",
}


def run(args) -> int:
    context = store.open_review(on_branch_change="warn")
    review = model.loads(context.path.read_text(encoding="utf-8"))
    payload = report.status_payload(review)
    # md 부재는 `sync`/`status`/`push` 가 모두 안내해야 한다(data-model.md §1 MUST).
    # json 이 정본이므로 exit 0 이다 — 잃은 것은 재생성 가능한 편집면뿐이다.
    if not store.review_md_path(context.root, context.iid).is_file():
        print(
            "⚠ review.md 가 없습니다. `mrq pull --render` 로 복원하세요. "
            "(review.json 은 온전합니다 — 답글과 상태는 그대로 있습니다)",
            file=sys.stderr,
        )

    if args.json:
        json.dump(payload, sys.stdout, ensure_ascii=False)
        sys.stdout.write("\n")
        return 0

    print(f"!{payload['iid']} {payload['title']}  ({payload['mr_state']})")
    print(
        f"head {payload['head_sha'][:7]} · pulled {_hhmm(payload['pulled_at'])} "
        f"· synced {_hhmm(payload['rendered_at'])}"
    )
    print()
    t, local, anchors, push_block = (
        payload["threads"],
        payload["local"],
        payload["anchors"],
        payload["push"],
    )
    print(
        f"threads   {t['total']} · unresolved {t['unresolved']} "
        f"· resolved-on-server {t['resolved_on_server']}"
    )
    print(
        f"local     done {local['done']} · replied {local['replied']} "
        f"· skipped {local['skipped']} · todo {local['todo']}"
    )
    print(
        f"anchors   exact {anchors['exact']} · fuzzy {anchors['fuzzy']} · stale {anchors['stale']}"
    )
    line = f"push      replies {push_block['replies']} · resolves {push_block['resolves']}"
    if push_block["skip"]:
        line += f" · skip {push_block['skip']}"
    print(line)
    # `payload` 는 `report.status_payload` 가 이미 `push.plan` 으로 계산했다.
    # 경고 문구에 쓸 "권한 없이 막힌 수"도 같은 함수에서 다시 얻는다(Minor 5)
    # — 여기서 직접 재계산하면 `resolvable`/`--resolve` 모드를 놓치고
    # `plan` 의 판정과 어긋난다.
    sheet = push.plan(review)
    for warning in payload["warnings"]:
        print(f"          ⚠ {_warning_text(review, warning, sheet)}")
    return 0


def _warning_text(review: model.Review, warning: dict, sheet: push.Plan) -> str:
    reason = warning["reason"]
    if reason == "no-resolve-permission":
        return (
            f"resolve {sheet.pending_resolves}건: 권한 없음 (Developer 이상 필요) → 전송하지 않음"
        )
    if reason == "mr-not-opened":
        return f"MR 이 {review.mr_state} 상태입니다 — push 는 확인을 요구합니다"
    return f"{warning['thread'][:8]} {_REASON_TEXT.get(reason, reason)}"


def _hhmm(value: str | None) -> str:
    # 포매터를 하나로 모은다. 두 벌이면 한쪽만 로컬 변환하는 상태로 갈라진다.
    return render.stamp(value, "%H:%M") if value else "-"
