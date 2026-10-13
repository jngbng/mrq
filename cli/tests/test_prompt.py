import pytest

from mrq import prompt
from mrq.errors import UsageError


def test_confirm_interactive_prompt_goes_to_stderr(monkeypatch, capsys):
    # Minor — `input(message)`로 넘기면 프롬프트 문구가 stdout 에 찍혀
    # 대화형 `--json` 세션에서 cli.md §2 의 "stdout 은 순수 JSON 객체 하나"
    # 를 깬다.
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "y")

    prompt.confirm("위험한 작업입니다.", force=False)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert "위험한 작업입니다." in captured.err


def test_confirm_declining_raises_usage_error(monkeypatch):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda: "n")

    with pytest.raises(UsageError):
        prompt.confirm("위험한 작업입니다.", force=False)


def test_confirm_force_skips_the_prompt_entirely(monkeypatch, capsys):
    monkeypatch.setattr("sys.stdin.isatty", lambda: True)

    prompt.confirm("위험한 작업입니다.", force=True)

    captured = capsys.readouterr()
    assert captured.out == ""
    assert captured.err == ""


def test_confirm_non_interactive_without_force_raises_without_blocking(monkeypatch):
    # 비대화형에서는 input() 을 아예 부르지 않는다 — 블로킹되면 세션이 멈춘다.
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    with pytest.raises(UsageError):
        prompt.confirm("위험한 작업입니다.", force=False)
