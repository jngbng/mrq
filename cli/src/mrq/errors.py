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


class GlabError(NetworkError):
    """`glab api` 호출 실패. HTTP 상태를 함께 나른다.

    `reason` 과 `retryable` 은 `docs/spec/data-model.md` §4.8 의 `local.push_error`
    가 그대로 쓰는 값이다. 소비자가 `message` 문자열을 파싱하게 만들지 않는다.
    """

    _REASONS = {403: "forbidden", 404: "not-found", 409: "conflict"}

    # 요청 타임아웃과 rate limit. GitLab 은 API 에 기본 rate limit 이 걸려 있어
    # 429 가 실제로 나온다. `reason` 열거값에 자리가 없지만 둘은 독립이다 —
    # `{reason: "unknown", retryable: true}` 로 표현한다.
    _TRANSIENT = frozenset({408, 429})

    def __init__(self, message: str, *, status: int | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.reason = "network" if status is None else self._REASONS.get(status, "unknown")
        # "시간이 지나면 같은 요청이 성공할 수 있는가" 로 정한다. 403·404·409 는
        # 다시 보내도 같은 결과다 — 참으로 표시하면 에이전트가 루프를 돈다.
        self.retryable = status is None or status >= 500 or status in self._TRANSIENT


class MrDetectionError(MrqError):
    """MR 이 0 건이거나 2 건 이상이다."""

    exit_code = 6


class SchemaVersionError(MrqError):
    """review.json 의 schema_version 이 이 mrq 와 맞지 않는다."""

    exit_code = 7


class CorruptStateError(UsageError):
    """review.json 을 읽을 수 없다 (JSON 문법 오류 또는 스키마 위반).

    종료 코드를 새로 만들지 않고 1 을 쓴다. editor.md 는 exit 2 와 3 만 분기하고
    손상 json 에 분기하는 소비자가 아직 없다. 종료 코드는 세 구현이 공유하는
    계약이라 소비자가 생길 때 올리는 쪽이 싸다.
    """

    exit_code = 1
