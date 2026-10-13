"""`push` 의 사전 판정. 네트워크도 파일도 만지지 않는다 (docs/spec/cli.md §8·§9).

`status` 의 `push` 블록과 `push` 의 판정은 **같은 함수**에서 나와야 한다(MUST).
두 곳에 따로 구현하면 "검토면은 9건이라고 했는데 8건 갔다" 가 조용히 생기고,
숫자가 틀리는 순간 전송 직전 검토면 자체가 의미를 잃는다. `status` 는 스냅샷
없이, `push` 는 스냅샷을 들고 부르므로 두 결과의 차이는 `server-changed` 하나다.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, field

from mrq import model

# 보낼 수 없다고 판정된 이유. 열거값이며 `--json` 과 `--dry-run` 이 같은 값을
# 쓴다 — 소비자가 메시지 문자열을 파싱하게 만들지 않는다 (cli.md §9 MUST NOT).
# `cli.md` §9 가 요구하는 다섯 값 전부다. `Plan.skip` 의 집계(§8)는 이 중
# 세 개로만 좁힌다 — 아래 `_COUNTED_SKIP_REASONS` 참조.
SKIP_REASONS = (
    "no-reply",
    "not-resolvable",
    "server-changed",
    "server-missing",
    "no-resolve-permission",
)

# `Plan.skip` 이 세는 세 가지 (cli.md §8): "로컬에서 이미 보낼 수 없다고 아는"
# 스레드의 수다. `server-changed` 는 재조회가 있어야만 나오는 판정이라 여기
# 없고(§9), `no-resolve-permission` 은 reply 는 보내지면서 resolve 액션만
# 막는 경우가 있어(`Decision.skip` 은 액션 단위) 넣지 않는다 — 두 이유 모두
# `decisions`/`targets()` 에는 그대로 남는다. 이 목록과 `SKIP_REASONS` 가
# 다른 것은 버그가 아니라 의도다.
_COUNTED_SKIP_REASONS = ("no-reply", "not-resolvable", "server-missing")


def body_hash(reply: str) -> str:
    """전송 본문의 sha256. `local.pushed_hash` 의 기준이다.

    해시 대상은 **실제로 stdin 에 넣는 바이트**다 (cli.md §9). 정규화하지
    않는다 — `v:` 해시(렌더 정규형)와는 다른 목적이다.
    """
    return hashlib.sha256(reply.encode()).hexdigest()


@dataclass
class Decision:
    """스레드 하나에 대해 이번 `push` 가 할 일.

    `skip` 은 **액션 단위**다 — 스레드 전체가 막혔다는 뜻이 아니다. 예:
    `repliable=False` + `resolvable=True` 인 `done` 스레드는 `skip="no-reply"`
    이면서 동시에 `resolve=True` 를 가질 수 있다 (reply 만 막혔다). 나중에
    실행기를 `for d in targets(): if d.skip: continue` 식으로 쓰면 그
    resolve 를 조용히 잃는다 — `reply`/`resolve`/`record_hash` 를 각각 봐야
    한다.
    """

    thread: str
    reply: str = ""  # 보낼 본문. "" 면 답글 전송 없음
    resolve: bool = False
    skip: str | None = None  # SKIP_REASONS 중 하나
    record_hash: str | None = None  # 전송 없이 기록할 pushed_hash (2차 방어)


@dataclass
class Plan:
    decisions: list[Decision] = field(default_factory=list)
    warnings: list[dict] = field(default_factory=list)

    @property
    def replies(self) -> int:
        return sum(1 for d in self.decisions if d.reply)

    @property
    def resolves(self) -> int:
        return sum(1 for d in self.decisions if d.resolve)

    @property
    def skip(self) -> int:
        return sum(1 for d in self.decisions if d.skip in _COUNTED_SKIP_REASONS)

    @property
    def pending_resolves(self) -> int:
        """권한만 없으면 resolve 가 시도됐을 스레드 수.

        `status` 의 "resolve N건: 권한 없음" 경고 문구가 이 수를 쓴다 — 서버
        에서 이미 빠지거나(`server-missing`) 바뀐(`server-changed`) 스레드,
        이미 resolve 된 스레드는 셈에 넣지 않는다. 직접 재계산하면(과거
        `commands/status.py` 가 그랬다) `resolvable`·`--resolve` 모드를
        놓치고 이 함수의 판정과 어긋난다.
        """
        return sum(1 for d in self.decisions if d.skip == "no-resolve-permission")

    def targets(self) -> list[Decision]:
        """실제로 쓰기 작업이 있는 결정만."""
        return [d for d in self.decisions if d.reply or d.resolve or d.record_hash]


def plan(
    review: model.Review,
    *,
    snapshot: list[model.Thread] | None = None,
    resolve: str = "auto",
    force: bool = False,
) -> Plan:
    """무엇을 보낼지 정한다. `snapshot` 은 `discussions.to_threads` 의 결과다.

    `snapshot=None` 은 "서버를 보지 않았다" 는 뜻이고 `server-changed` 판정만
    빠진다. `resolve` 는 `auto | skip | require` 이며 `require` 의 권한 검사는
    호출자가 전송 전에 한다(exit 1) — 여기서는 `auto` 와 같게 다룬다.
    """
    out = Plan()
    fresh = {t.id: t for t in snapshot} if snapshot is not None else None

    for thread in review.threads:
        local = thread.local
        has_reply = bool(local.reply.strip()) and local.state in ("done", "replied")
        wants_resolve = local.state == "done" and not thread.server.resolved and resolve != "skip"
        if not (has_reply or wants_resolve):
            continue

        decision = Decision(thread=thread.id)
        # 이 스레드에 대해 이번 루프에서 내는 경고. `server-missing` 이 뒤에서
        # 덮으면 통째로 버린다 — 한 스레드에 서로 다른 이유 두 개가 동시에
        # 찍히면 `skip` 수(하나)와 맞지 않아 보인다.
        thread_warnings: list[dict] = []

        if has_reply:
            if not thread.server.repliable:
                decision.skip = "no-reply"
                thread_warnings.append({"thread": thread.id, "reason": "no-reply"})
            elif local.pushed_hash == body_hash(local.reply):
                # 1차 방어. 이미 보낸 본문이다 — 조용히 생략한다.
                pass
            else:
                decision.reply = local.reply

        # 권한 부족으로만 막히는지 추적한다 — 서버에서 이미 빠지거나 바뀌거나
        # 이미 resolve 된 경우는 권한과 무관하게 시도되지 않으므로 아래에서
        # `False` 로 꺾인다(Minor 3).
        resolve_eligible = False
        if wants_resolve:
            if not thread.server.resolvable:
                decision.skip = decision.skip or "not-resolvable"
                thread_warnings.append({"thread": thread.id, "reason": "not-resolvable"})
            else:
                resolve_eligible = True
                decision.resolve = True  # 권한·서버 상태로 아래에서 깎일 수 있다

        # 로컬에서 이미 아는 제약이 먼저다. 그 판정은 스냅샷 없이 부르는
        # `status` 와 결과가 같아야 한다.
        if thread.server.missing:
            decision.skip = "server-missing"
            decision.reply, decision.resolve, decision.record_hash = "", False, None
            resolve_eligible = False
            thread_warnings = [{"thread": thread.id, "reason": "server-missing"}]
        elif fresh is not None:
            _judge_against_server(decision, thread, fresh.get(thread.id), force=force)
            if decision.skip == "server-missing":
                thread_warnings = [{"thread": thread.id, "reason": "server-missing"}]
            if not decision.resolve:
                resolve_eligible = False

        if resolve_eligible and not review.me.can_resolve:
            decision.resolve = False
            decision.skip = decision.skip or "no-resolve-permission"

        out.warnings.extend(thread_warnings)

        if decision.reply or decision.resolve or decision.skip or decision.record_hash:
            out.decisions.append(decision)

    out.warnings += _standing_warnings(review, out.pending_resolves)
    return out


def _judge_against_server(
    decision: Decision,
    thread: model.Thread,
    current: model.Thread | None,
    *,
    force: bool,
) -> None:
    """스냅샷이 있을 때만 하는 판정 (cli.md §9 3단계)."""
    if current is None:
        # 보낼 곳이 없다. `--force` 로도 보내지 않는다 — `--force` 가 무시하는
        # 것은 "서버가 바뀌었다" 뿐이다 (결정 0011).
        decision.skip = "server-missing"
        decision.reply, decision.resolve, decision.record_hash = "", False, None
        return
    changed = (
        current.server.updated_at != thread.server.updated_at
        or current.server.note_count != thread.server.note_count
    )
    if changed and not force:
        decision.skip = "server-changed"
        decision.reply, decision.resolve = "", False
        return
    if decision.reply and _already_posted(current, decision.reply):
        # 2차 방어. POST 는 성공했는데 `pushed_hash` 기록 직전에 죽은 경우다.
        # 해시를 기록해야 한다(MUST) — 건너뛰기만 하면 다음 실행도 매번
        # 스냅샷에 의존하고, 그 note 가 스냅샷에서 빠지면 중복 전송이 된다.
        # `--force` 는 "서버가 바뀌었다" 판정만 무시한다 — 이 방어는 그 if
        # 문 바깥이라 force 와 무관하게 항상 적용된다.
        decision.record_hash = body_hash(decision.reply)
        decision.reply = ""
    if decision.resolve and current.server.resolved:
        decision.resolve = False


def _already_posted(current: model.Thread, reply: str) -> bool:
    """스냅샷에 같은 본문의 내 note 가 있는가.

    양쪽을 `strip()` 해 느슨하게 본다 — GitLab 이 끝 공백을 다듬어 돌려주면
    엄격 비교가 중복 전송을 허용한다. 느슨한 쪽의 실패(전송을 한 번 빼먹고
    사용자가 `status` 에서 본다)가 엄격한 쪽(같은 답글을 두 번 올린다)보다 싸다.
    """
    needle = reply.strip()
    return any(note.mine and note.body.strip() == needle for note in current.notes)


def _standing_warnings(review: model.Review, pending_resolves: int) -> list[dict]:
    """전송 대상과 무관하게 사용자가 알아야 하는 것들."""
    out: list[dict] = []
    for thread in review.threads:
        if thread.local.reply.strip() and thread.local.state == "todo":
            # push 는 todo 에 아무것도 하지 않는다(§4.7). replies 에도 세어지지
            # 않으므로 검토면에서 보이지 않는 자리다.
            out.append({"thread": thread.id, "reason": "todo-with-reply"})
        if thread.local.push_error is not None:
            # push 자신의 출력은 그 순간에만 보인다. 이것이 없으면 403 이
            # json 안에만 남는다 (cli.md §8).
            out.append({"thread": thread.id, "reason": "push-failed"})
    if pending_resolves:
        # 개별 이유는 각 Decision.skip 에 이미 있다 — 여기는 "총 N건" 집계
        # 경고 하나만 낸다(결정됨: thread=None, 스레드별로 중복하지 않는다).
        out.append({"thread": None, "reason": "no-resolve-permission"})
    if review.mr_state != "opened":
        out.append({"thread": None, "reason": "mr-not-opened"})
    return out
