import pytest

from mrq.__main__ import main
from mrq.errors import MrqError, ParseError, SchemaVersionError


def test_no_command_is_usage_error(capsys):
    assert main([]) == 1
    assert "명령을 지정하세요" in capsys.readouterr().err


def test_unknown_command_does_not_use_exit_code_2(capsys):
    # argparse 기본값은 exit 2인데, 우리 계약에서 2는 "md 파싱 에러"다.
    # 사용법 오류가 2로 나가면 에디터가 "review.md를 고쳐라"를 띄운다.
    assert main(["bogus"]) == 1


def test_version_exits_zero():
    with pytest.raises(SystemExit) as excinfo:
        main(["--version"])
    assert excinfo.value.code == 0


@pytest.mark.parametrize(
    ("exc", "code"),
    [(ParseError, 2), (SchemaVersionError, 7), (MrqError, 1)],
)
def test_error_classes_carry_exit_codes(exc, code, monkeypatch, capsys):
    def boom(argv):
        raise exc("터졌습니다")

    monkeypatch.setattr("mrq.cli.dispatch", boom)
    assert main([]) == code
    assert "터졌습니다" in capsys.readouterr().err
