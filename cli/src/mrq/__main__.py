"""엔트리포인트. MrqError 를 종료 코드로 변환하는 유일한 지점."""

from __future__ import annotations

import sys

from mrq import cli
from mrq.errors import MrqError


def main(argv: list[str] | None = None) -> int:
    try:
        return cli.dispatch(sys.argv[1:] if argv is None else argv)
    except MrqError as exc:
        print(str(exc), file=sys.stderr)
        return exc.exit_code
    except KeyboardInterrupt:
        return 130


if __name__ == "__main__":
    sys.exit(main())
