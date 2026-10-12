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
    # --all 은 렌더링에만 영향을 준다. review.json 은 항상 모든 스레드를 담으므로
    # 렌더러가 들어오는 계획 2 까지는 받아만 두고 아무 일도 하지 않는다.
    pull.add_argument("--all", action="store_true", help="resolve 된 스레드도 렌더한다")
    pull.add_argument("--render", action="store_true", help="review.md 만 다시 그린다")
    pull.add_argument("--no-render", action="store_true", help="review.md 를 그리지 않는다")

    reanchor = sub.add_parser("reanchor", help="위치만 다시 계산한다 (네트워크 없음)")
    reanchor.add_argument("--json", action="store_true")

    return parser


def dispatch(argv: list[str]) -> int:
    args = build_parser().parse_args(argv)
    if args.command is None:
        raise UsageError("명령을 지정하세요. `mrq --help` 를 보세요.")

    from mrq.commands import pull as pull_command
    from mrq.commands import reanchor as reanchor_command

    handlers = {"pull": pull_command.run, "reanchor": reanchor_command.run}
    return handlers[args.command](args)
