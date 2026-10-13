"""argparse 디스패치. 서브커맨드는 각 명령 과제에서 등록한다."""

from __future__ import annotations

import argparse

from mrq import __version__
from mrq.errors import UsageError


class _Parser(argparse.ArgumentParser):
    """argparse 는 사용법 오류에 exit 2 를 쓴다. 우리 계약에서 2 는 파싱 에러다."""

    def error(self, message: str) -> None:  # type: ignore[override]
        raise UsageError(message)


def build_parser() -> argparse.ArgumentParser:
    parser = _Parser(prog="mrq")
    parser.add_argument("--version", action="version", version=__version__)
    sub = parser.add_subparsers(dest="command")

    pull = sub.add_parser("pull", help="GitLab 에서 코멘트를 받아 review.json 을 쓴다")
    pull.add_argument("--mr", type=int, default=None, help="MR iid 를 직접 지정한다")
    pull.add_argument("--all", action="store_true", help="resolve 된 스레드도 렌더한다")
    pull.add_argument("--render", action="store_true", help="review.md 만 다시 그린다")
    pull.add_argument("--no-render", action="store_true", help="review.md 를 그리지 않는다")

    reanchor = sub.add_parser("reanchor", help="위치만 다시 계산한다 (네트워크 없음)")
    reanchor.add_argument("--json", action="store_true")

    sync = sub.add_parser("sync", help="review.md 를 json 에 반영하고 재앵커링한다")
    sync.add_argument("--json", action="store_true")
    sync.add_argument("--prefer", choices=["md", "json"], default=None)
    sync.add_argument(
        "--thread", action="append", default=None, help="--prefer 를 적용할 스레드 (반복 가능)"
    )

    status = sub.add_parser("status", help="전송 직전 검토면을 보여준다")
    status.add_argument("--json", action="store_true")

    listing = sub.add_parser("list", help="스레드 목록 (AI 에이전트의 읽기 경로)")
    listing.add_argument("--json", action="store_true")
    listing.add_argument("--all", action="store_true", help="서버에서 resolve 된 것도 포함한다")
    listing.add_argument("--state", choices=["todo", "done", "replied", "skipped"], default=None)
    listing.add_argument("--confidence", choices=["exact", "fuzzy", "stale"], default=None)

    reply = sub.add_parser("reply", help="스레드에 답글을 기록한다 (전송은 push)")
    reply.add_argument("thread")
    # 둘을 함께 주면 조용히 -m 이 이겼다 — 어느 본문이 기록됐는지 모르는 채
    # 스크립트가 지나간다. 배타 그룹이 exit 1 로 끊는다.
    body = reply.add_mutually_exclusive_group()
    body.add_argument("-m", "--message", default=None)
    body.add_argument("-F", "--file", default=None, help="파일 또는 `-` (stdin)")
    reply.add_argument("--state", choices=["todo", "done", "replied", "skipped"], default=None)

    state = sub.add_parser("state", help="스레드의 로컬 상태를 바꾼다")
    state.add_argument("thread")
    state.add_argument("state", choices=["todo", "done", "replied", "skipped"])

    push = sub.add_parser("push", help="답글과 resolve 를 GitLab 에 전송한다")
    push.add_argument("--json", action="store_true")
    push.add_argument("--dry-run", action="store_true", help="보낼 것만 보여준다")
    push.add_argument(
        "--force",
        action="store_true",
        help="서버에서 변경된 스레드도 보내고, MR 이 열려 있지 않아도 진행한다",
    )
    push.add_argument("--draft", action="store_true", help="draft 로 묶어 둔다 (발행은 --publish)")
    push.add_argument("--publish", action="store_true", help="draft 를 일괄 발행한다")
    push.add_argument("--resolve", choices=["auto", "skip", "require"], default="auto")

    sub.add_parser("doctor", help="환경을 진단한다")

    return parser


def dispatch(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        raise UsageError("명령을 지정하세요. `mrq --help` 를 보세요.")

    from mrq.commands import doctor as doctor_command
    from mrq.commands import listing as listing_command
    from mrq.commands import pull as pull_command
    from mrq.commands import push as push_command
    from mrq.commands import reanchor as reanchor_command
    from mrq.commands import reply as reply_command
    from mrq.commands import state as state_command
    from mrq.commands import status as status_command
    from mrq.commands import sync as sync_command

    handlers = {
        "pull": pull_command.run,
        "reanchor": reanchor_command.run,
        "sync": sync_command.run,
        "status": status_command.run,
        "list": listing_command.run,
        "reply": reply_command.run,
        "state": state_command.run,
        "push": push_command.run,
        "doctor": doctor_command.run,
    }
    return handlers[args.command](args)
