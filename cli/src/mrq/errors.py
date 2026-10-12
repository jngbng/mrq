"""종료 코드를 갖는 예외 계층. docs/spec/cli.md §2 의 표를 그대로 옮긴다."""


class MrqError(Exception):
    """사용자에게 보여줄 메시지를 갖는 실패. exit_code 로 종료한다."""

    exit_code = 1


class UsageError(MrqError):
    """사용법·설정 오류."""

    exit_code = 1


class ParseError(MrqError):
    """review.md 파싱 에러. 아무것도 쓰지 않았음을 뜻한다."""

    exit_code = 2


class ConflictError(MrqError):
    """md 와 CLI 가 같은 스레드를 다르게 고쳤다. 아무것도 쓰지 않았다."""

    exit_code = 3


class PartialPushError(MrqError):
    """push 일부 실패."""

    exit_code = 4


class NetworkError(MrqError):
    """glab 호출 실패 또는 인증 실패."""

    exit_code = 5


class MrDetectionError(MrqError):
    """MR 이 0 건이거나 2 건 이상이다."""

    exit_code = 6


class SchemaVersionError(MrqError):
    """review.json 의 schema_version 이 이 mrq 와 맞지 않는다."""

    exit_code = 7
