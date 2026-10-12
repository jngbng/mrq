"""충돌 판정. docs/spec/data-model.md §5.

사람은 `review.md` 를, AI 는 CLI(`reply`/`state`) 를 통해 같은 json 을 바꿀 수
있다. **같은 스레드를 서로 다르게** 고친 경우만 충돌이다. 서로 다른 스레드를
고치는 것은 정상 워크플로이며 충돌이 아니다(MUST).
"""

from __future__ import annotations

from dataclasses import dataclass

from mrq import mdparse, model, render


@dataclass
class Applied:
    thread: str
    state: str
    reply: str
    reply_changed: bool

    def as_dict(self) -> dict:
        return {"thread": self.thread, "state": self.state, "reply_changed": self.reply_changed}


@dataclass
class Conflict:
    thread: str
    md_state: str
    md_reply: str
    json_state: str
    json_reply: str

    def as_dict(self) -> dict:
        return {
            "thread": self.thread,
            "md": {"state": self.md_state, "reply": self.md_reply},
            "json": {"state": self.json_state, "reply": self.json_reply},
        }


def md_values(thread: model.Thread, block: mdparse.Block) -> tuple[str, str]:
    """md 쪽의 (state, reply). 경고로 떨어진 항목은 json 값을 유지한다 (§7)."""
    state = block.state if block.state is not None else thread.local.state
    reply = block.reply if block.reply is not None else render.normalize_reply(thread.local.reply)
    return state, reply


def classify(thread: model.Thread, block: mdparse.Block) -> str:
    """`"keep-json" | "apply-md" | "conflict"` (§5.2 판정 표).

    "렌더 후 json 변경"은 시각이 아니라 `v` 핑거프린트로 판정한다. `cli.md` §10
    은 `reply`/`state`가 `touched_at`을 기록한 **뒤에** md 를 재렌더해
    `rendered_at`을 갱신하도록 못박으므로, 정상 경로에서는 항상 `touched_at <=
    rendered_at`이 되어 `touched_at > rendered_at` 비교가 영원히 거짓이 된다 —
    §5.2 의 4·6행(충돌)이 죽은 코드가 되고 AI 의 답글이 조용히 지워진다. 대신
    "md 가 렌더될 때 json 이 어땠는지"의 핑거프린트인 `v` 를 지금의 json 상태와
    다시 비교해 "그 뒤 json 이 움직였는지"를 직접 묻는다 — 시계를 보지 않는다.
    근거는 `docs/decisions/0008-conflict-signal-v-hash-not-timestamp.md`.
    """
    state, reply = md_values(thread, block)
    if block.v is not None and block.v == render.vhash(state, reply):
        return "keep-json"  # 행 1·2 — 사람이 md 를 편집하지 않았다
    if state == thread.local.state and reply == render.normalize_reply(thread.local.reply):
        # 양쪽이 같은 값에 도달했다 (사람이 AI 가 쓴 것과 똑같이 적은 경우 등).
        # 보여줄 차이가 없으므로 충돌이 아니다 — 같은 두 쪽을 나란히 띄우는
        # 화면은 사용자에게 고를 것을 주지 못한다. 여기 닿는 것은 `v` 토큰이
        # 낡거나 없는 경우뿐이다 (아니면 위에서 이미 돌아갔다).
        return "keep-json"
    json_v = render.vhash(thread.local.state, thread.local.reply)
    cli_changed = thread.local.touched_by == "cli" and (block.v is None or block.v != json_v)
    return "conflict" if cli_changed else "apply-md"  # 행 3·4·5·6


def plan_sync(
    review,
    parsed: mdparse.Parsed,
    *,
    prefer: str | None = None,
    only: tuple[str, ...] = (),
) -> tuple[list[Applied], list[Conflict], list[mdparse.Message]]:
    """무엇을 반영하고 무엇이 충돌인지 계산한다. 아무것도 변경하지 않는다."""
    by_id = {t.id: t for t in review.threads}
    applied: list[Applied] = []
    conflicts: list[Conflict] = []
    warnings: list[mdparse.Message] = []

    for block in parsed.blocks:
        thread = by_id.get(block.thread_id)
        if thread is None:
            warnings.append(
                mdparse.Message(
                    block.line, f"review.json 에 없는 앵커 ID {block.thread_id} — 무시합니다"
                )
            )
            continue
        decision = classify(thread, block)
        if decision == "conflict" and prefer and _targeted(block.thread_id, only):
            decision = "apply-md" if prefer == "md" else "keep-json"
        state, reply = md_values(thread, block)
        if decision == "apply-md":
            applied.append(
                Applied(
                    thread=thread.id,
                    state=state,
                    reply=reply,
                    reply_changed=reply != render.normalize_reply(thread.local.reply),
                )
            )
        elif decision == "conflict":
            conflicts.append(
                Conflict(
                    thread=thread.id,
                    md_state=state,
                    md_reply=reply,
                    json_state=thread.local.state,
                    json_reply=render.normalize_reply(thread.local.reply),
                )
            )
    return applied, conflicts, warnings


def _targeted(thread_id: str, only: tuple[str, ...]) -> bool:
    """`--thread` 가 없으면 충돌 전체, 주면 지정한 것만 (§5.3).

    `only` 는 `commands.sync` 가 `threads.resolve_ref` 로 미리 완전한 discussion
    id 로 해석해 넘긴다 — 접두사 매칭은 여기서 하지 않는다. 모호한 접두사가
    엉뚱한 스레드에 `--prefer` 를 적용하는 사고를 막는 유일한 지점을
    `threads.py` 하나로 모으기 위해서다.
    """
    return not only or thread_id in only
