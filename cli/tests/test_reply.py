from mrq import model, render, store
from mrq.__main__ import main
from tests.test_status import ready  # noqa: F401


def _json(root) -> model.Review:
    return model.loads(store.review_json_path(root, 1234).read_text(encoding="utf-8"))


def _thread(root, thread_id="a1b2c3d4e5f6"):
    return next(t for t in _json(root).threads if t.id == thread_id)


def test_reply_with_message_sets_local_and_touch(ready):  # noqa: F811
    assert main(["reply", "a1b2", "-m", "확인했습니다"]) == 0
    thread = _thread(ready)
    assert thread.local.reply == "확인했습니다"
    assert thread.local.touched_by == "cli"
    assert thread.local.touched_at is not None
    assert thread.local.state == "todo"


def test_reply_with_state_sets_both(ready):  # noqa: F811
    assert main(["reply", "a1b2", "-m", "확인", "--state", "done"]) == 0
    assert _thread(ready).local.state == "done"


def test_reply_reads_stdin_with_dash(ready, monkeypatch):  # noqa: F811
    import io

    monkeypatch.setattr("sys.stdin", io.StringIO("여러 줄\n\n본문입니다\n"))
    assert main(["reply", "a1b2", "-F", "-"]) == 0
    assert _thread(ready).local.reply == "여러 줄\n\n본문입니다"


def test_reply_reads_a_file(ready, tmp_path):  # noqa: F811
    path = tmp_path / "body.md"
    path.write_text("파일에서 읽은 본문\n", encoding="utf-8")
    assert main(["reply", "a1b2", "-F", str(path)]) == 0
    assert _thread(ready).local.reply == "파일에서 읽은 본문"


def test_reply_rerenders_md_with_updated_v_hash(ready):  # noqa: F811
    assert main(["reply", "a1b2", "-m", "확인", "--state", "done"]) == 0
    md = store.review_md_path(ready, 1234).read_text(encoding="utf-8")
    assert f"<!-- mrq:a1b2c3d4e5f6 v:{render.vhash('done', '확인')} -->" in md
    assert "## [x] src/api/client.py:102" in md
    # 재렌더 직후 sync 는 아무 변화도 만들지 않아야 한다 (거짓 충돌 금지).
    assert main(["sync"]) == 0
    assert _thread(ready).local.touched_by == "cli"


def test_reply_rejects_empty_thread_ref(ready):  # noqa: F811
    # `threads.resolve_ref`(과제 8)가 빈 문자열을 명시적으로 거부한다 — 스레드가
    # 하나뿐인 리뷰에서도 ""가 그 하나와 "유일하게 일치"로 통과하면 안 된다.
    assert main(["reply", "", "-m", "x"]) == 1


def test_reply_rejects_ambiguous_prefix(ready, capsys):  # noqa: F811
    # 샘플 리뷰에 접두사가 겹치는 스레드를 하나 더 추가해 모호성을 만든다.
    review = _json(ready)
    import copy

    clone = copy.deepcopy(next(t for t in review.threads if t.id == "a1b2c3d4e5f6"))
    clone.id = "a1b2ffffffff"
    clone.root_note_id = 999999
    review.threads.append(clone)
    store.atomic_write_text(store.review_json_path(ready, 1234), model.dumps(review))

    assert main(["reply", "a1b2", "-m", "x"]) == 1
    assert "걸립니다" in capsys.readouterr().err


def test_reply_rejects_unknown_thread(ready):  # noqa: F811
    assert main(["reply", "zzzz", "-m", "x"]) == 1


def test_reply_requires_a_body(ready):  # noqa: F811
    assert main(["reply", "a1b2"]) == 1


def test_state_sets_state_and_rerenders(ready):  # noqa: F811
    assert main(["state", "a1b2", "skipped"]) == 0
    assert _thread(ready).local.state == "skipped"
    assert "## [-] src/api/client.py:102" in store.review_md_path(ready, 1234).read_text(
        encoding="utf-8"
    )


def test_state_rejects_unknown_value(ready):  # noqa: F811
    assert main(["state", "a1b2", "DONE"]) == 1


def test_state_without_review_state_exits_1(git_repo, commit, monkeypatch):
    commit({"a.py": "x\n"})
    monkeypatch.chdir(git_repo)
    assert main(["state", "a1b2", "done"]) == 1


def test_reply_rejects_an_empty_message_without_destroying_the_pending_reply(ready):  # noqa: F811
    # 가장 나쁜 실패 양상: 사람이 아직 보내지 않은 답글이 빈 본문으로 조용히
    # 덮여 사라진다. 평범한 배관 실수(-m "" / 빈 파이프)로 닿는 경로였다.
    assert main(["reply", "a1b2", "-m", "사람이 쓴 미전송 답글"]) == 0
    before = _thread(ready).local

    assert main(["reply", "a1b2", "-m", ""]) == 1

    after = _thread(ready).local
    assert after.reply == "사람이 쓴 미전송 답글"  # 손실이 **없다**
    assert (after.state, after.touched_at) == (before.state, before.touched_at)


def test_reply_rejects_empty_stdin_without_destroying_the_pending_reply(ready, monkeypatch):  # noqa: F811
    import io

    assert main(["reply", "a1b2", "-m", "사람이 쓴 미전송 답글"]) == 0
    monkeypatch.setattr("sys.stdin", io.StringIO("\n  \n"))

    assert main(["reply", "a1b2", "-F", "-"]) == 1

    assert _thread(ready).local.reply == "사람이 쓴 미전송 답글"


def test_reply_empty_body_message_points_at_state(ready, capsys):  # noqa: F811
    assert main(["reply", "a1b2", "-m", "   "]) == 1
    assert "mrq state" in capsys.readouterr().err


def test_reply_rejects_message_and_file_together(ready, tmp_path, capsys):  # noqa: F811
    path = tmp_path / "body.md"
    path.write_text("파일 본문\n", encoding="utf-8")
    before = _thread(ready).local.reply

    assert main(["reply", "a1b2", "-m", "인자 본문", "-F", str(path)]) == 1

    assert _thread(ready).local.reply == before  # 어느 쪽도 기록되지 않는다
    assert "not allowed with" in capsys.readouterr().err


def test_reply_refuses_to_write_after_the_checkout_moved(ready, checkout, capsys):  # noqa: F811
    # 엉뚱한 MR 의 리뷰에 답글을 쓰는 것이 I2 의 실제 손해다.
    before = _thread(ready).local.reply
    checkout("feat/other")

    assert main(["reply", "a1b2", "-m", "다른 브랜치에서 쓴 답글"]) == 1

    assert _thread(ready).local.reply == before
    err = capsys.readouterr().err
    assert "feat/other" in err and "feat/retry" in err and "mrq pull" in err


def test_state_refuses_to_write_after_the_checkout_moved(ready, checkout):  # noqa: F811
    before = _thread(ready).local.state
    checkout("feat/other")
    assert main(["state", "a1b2", "done"]) == 1
    assert _thread(ready).local.state == before


def test_reply_still_writes_in_detached_head(ready, capsys):  # noqa: F811
    # 브랜치 가드의 의도적인 예외 (store.check_branch): detached HEAD 는 "다른
    # MR 의 브랜치" 가 아니다. 막으면 커밋 하나를 체크아웃해 확인하던 사람이
    # 답글을 기록할 우회로가 없다 (`--force` 가 없다).
    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ready, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "--detach", sha], cwd=ready, check=True)

    assert main(["reply", "a1b2", "-m", "detached 에서도 기록된다"]) == 0
    assert _thread(ready).local.reply == "detached 에서도 기록된다"
    assert "detached HEAD" in capsys.readouterr().err
