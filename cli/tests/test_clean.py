from pathlib import Path

import pytest

from mrq import model, store, surface
from mrq.__main__ import main
from mrq.commands import clean as clean_command

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


def _place(root, iid: int, *, state: str = "opened", unsent: bool = False):
    review = model.loads(SAMPLE.read_text(encoding="utf-8"))
    review.iid = iid
    review.mr_state = state
    # `rendered.json` 에는 렌더러 테스트가 쓰는 `replied`/`done` + 답글이 이미
    # 섞여 있다 (test_push.py 의 `_blank` 와 같은 이유). 비우지 않으면
    # unsent=False 호출도 미전송 스레드 2개를 물고 들어와 확인을 요구한다.
    for thread in review.threads:
        thread.local.state = "todo"
        thread.local.reply = ""
        thread.local.pushed_hash = None
        thread.local.push_error = None
    if unsent:
        review.threads[1].local.state = "done"
        review.threads[1].local.reply = "아직 보내지 않았다"
    with store.review_lock(root, iid):
        surface.write(root, review, include_resolved=True)
    return review


@pytest.fixture
def stocked(git_repo, commit, checkout, glab, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    _place(git_repo, 1235)
    store.write_current(git_repo, 1234)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "opened", "source_branch": "b"},
    )
    return git_repo


def test_clean_removes_merged_and_clears_current(stocked):
    assert main(["clean", "--merged"]) == 0

    assert not store.review_dir(stocked, 1234).exists()
    assert store.review_dir(stocked, 1235).exists()
    # current 가 가리키는 MR 을 제거하면 current 도 지운다(MUST) — 끊어진
    # 심링크를 남기지 않는다.
    assert store.read_current(stocked) is None


def test_clean_leaves_current_untouched_when_it_survives(stocked):
    # `current` MUST 의 나머지 절반 — 지금까지는 `stocked` 가 늘 제거 대상인
    # 1234 를 current 로 둬서, "살아남는 MR 을 current 가 가리킬 때는 건드리지
    # 않는다"를 검증하는 테스트가 없었다.
    store.write_current(stocked, 1235)

    assert main(["clean", "--merged"]) == 0

    assert not store.review_dir(stocked, 1234).exists()
    assert store.review_dir(stocked, 1235).exists()
    assert store.read_current(stocked) == 1235


def test_clean_skips_target_with_new_unsent_work_since_scan(stocked, monkeypatch, capsys):
    # json 을 바꾸는 명령은 lock 을 잡아야 한다(data-model.md §1 MUST). 스캔
    # 시점엔 미전송 작업이 없어 확인 없이 삭제 대상에 들어갔지만, lock 을 잡고
    # 삭제하기 직전 다시 확인했을 때 늘어나 있으면(에디터 `sync`가 그 사이에
    # 답글을 써넣은 경우를 흉내 낸다) 그 대상은 건너뛰어야 한다 — 스캔이
    # 통과시킨 뒤 조용히 사라지는 답글을 만들면 안 된다.
    #
    # 실제 동시성(다른 프로세스가 lock 사이에 파일을 바꾸는 것)을 테스트에서
    # 그대로 재현할 수 없으므로 `_unsent`를 패치해 "스캔 때는 0, 삭제 직전
    # 재확인 때는 그보다 큼"을 흉내 낸다 — `clean.run`이 스캔과 재확인에서
    # 각각 한 번씩 `_unsent`를 부르는 두 호출 지점을 그대로 쓴다.
    calls = {"n": 0}
    original_unsent = clean_command._unsent

    def fake_unsent(root, iid):
        if iid != 1234:
            return original_unsent(root, iid)
        calls["n"] += 1
        return 0 if calls["n"] == 1 else 3

    monkeypatch.setattr(clean_command, "_unsent", fake_unsent)

    assert main(["clean", "--merged"]) == 0

    assert store.review_dir(stocked, 1234).exists()
    stderr = capsys.readouterr().err
    assert "1234" in stderr
    assert "0→3" in stderr


def test_clean_dry_run_removes_nothing(stocked, capsys):
    assert main(["clean", "--merged", "--dry-run"]) == 0

    assert store.review_dir(stocked, 1234).exists()
    assert "1234" in capsys.readouterr().out


def test_clean_refuses_when_unsent_work_remains(git_repo, commit, checkout, glab, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234, unsent=True)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["clean", "--merged"]) == 1
    assert store.review_dir(git_repo, 1234).exists()

    assert main(["clean", "--merged", "--force"]) == 0
    assert not store.review_dir(git_repo, 1234).exists()


def test_clean_treats_corrupt_review_json_as_unsent(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # 손상된 review.json 은 "미전송 없음" 으로 조용히 넘기면 안 된다 —
    # 복구 불가능한 답글이 그 안에 있을 수 있다(data-model.md §1). 확인
    # 게이트에 걸려야 하고(exit 1, 비대화형), `--force` 로만 지울 수 있다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    store.review_dir(git_repo, 1234).mkdir(parents=True)
    store.review_json_path(git_repo, 1234).write_text("{ 이건 json 이 아니다", encoding="utf-8")
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    monkeypatch.setattr("sys.stdin.isatty", lambda: False)

    assert main(["clean", "--merged"]) == 1
    assert store.review_dir(git_repo, 1234).exists()
    assert "1234" in capsys.readouterr().err

    assert main(["clean", "--merged", "--force"]) == 0
    assert not store.review_dir(git_repo, 1234).exists()


def test_clean_continues_after_one_target_fails_to_remove(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # 하나를 못 지워도(디스크 오류 등) 나머지는 지워야 한다 — 트레이스백으로
    # 중간에 죽으면 이미 확인까지 끝낸 나머지 대상도 그대로 남는다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    _place(git_repo, 1235)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "merged", "source_branch": "b"},
    )

    original_rmtree = clean_command.shutil.rmtree

    def flaky_rmtree(path, *args, **kwargs):
        if Path(path).name == "1234":
            raise OSError("디스크가 사용 중입니다")
        return original_rmtree(path, *args, **kwargs)

    monkeypatch.setattr(clean_command.shutil, "rmtree", flaky_rmtree)

    assert main(["clean", "--merged"]) == 0

    assert store.review_dir(git_repo, 1234).exists()
    assert not store.review_dir(git_repo, 1235).exists()
    assert "1234" in capsys.readouterr().err


def test_clean_continues_after_lock_contention_on_one_target(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # Important 5 — `store.review_lock`은 경쟁 시 `UsageError`를 던진다.
    # 루프 안에 `try`가 없으면 그 예외가 `run` 밖으로 그대로 빠져나가 —
    # 이미 지운 앞선 대상의 삭제는 그대로 남지만 `removed: N개` 줄은 찍히지
    # 않고 종료 코드도 1이 된다. 되돌릴 수 없는 명령에서 "일부는 지워졌는데
    # 실패로 보인다"는 틀린 신호다 — 다른 모든 대상별 실패처럼 건너뛰고
    # 계속해야 한다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1000)
    _place(git_repo, 2000)
    glab.route(
        "GET projects/:fullpath/merge_requests/1000",
        {"iid": 1000, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    glab.route(
        "GET projects/:fullpath/merge_requests/2000",
        {"iid": 2000, "title": "t", "web_url": "u", "state": "merged", "source_branch": "b"},
    )

    from contextlib import contextmanager

    from mrq.errors import UsageError

    original_lock = clean_command.store.review_lock

    @contextmanager
    def flaky_lock(root, iid):
        if iid == 2000:
            raise UsageError(f".mrq/{iid}/lock 락을 얻지 못했습니다 (테스트)")
        with original_lock(root, iid):
            yield

    monkeypatch.setattr(clean_command.store, "review_lock", flaky_lock)

    assert main(["clean", "--merged"]) == 0

    assert not store.review_dir(git_repo, 1000).exists()
    assert store.review_dir(git_repo, 2000).exists()
    captured = capsys.readouterr()
    assert "2000" in captured.err
    assert "removed: 1개" in captured.out


def test_clean_warns_on_malformed_iid_directories(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # `01235`(표준 형식이 아닌 이름)는 `int()` 왕복으로 `store.review_dir`이
    # 가리키는 디렉터리와 달라진다 — 건드리면 엉뚱한 디렉터리를 잠그고 지울
    # 수 있으니 거부하고 경고만 낸다. `not-an-iid` 처럼 숫자가 아닌 이름도
    # 마찬가지다. 둘 다 있어도 정상 대상(1234) 처리는 계속돼야 한다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    glab.route(
        "GET projects/:fullpath/merge_requests/1234",
        {"iid": 1234, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    (store.mrq_dir(git_repo) / "01235").mkdir(parents=True)
    (store.mrq_dir(git_repo) / "01235" / "review.json").write_text("{}", encoding="utf-8")
    (store.mrq_dir(git_repo) / "not-an-iid").mkdir(parents=True)
    (store.mrq_dir(git_repo) / "not-an-iid" / "review.json").write_text("{}", encoding="utf-8")

    assert main(["clean", "--merged", "--dry-run"]) == 0

    captured = capsys.readouterr()
    assert "01235" in captured.err
    assert "not-an-iid" in captured.err
    assert "!1234" in captured.out


def test_clean_lists_targets_in_numeric_order(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # `sorted(glob(...))` 는 경로 문자열 사전순이라 "1235" 가 "999" 보다 먼저
    # 나온다. iid 로 정렬해 보여줄 순서가 숫자 순서와 맞아야 한다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1235)
    _place(git_repo, 999)
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "merged", "source_branch": "a"},
    )
    glab.route(
        "GET projects/:fullpath/merge_requests/999",
        {"iid": 999, "title": "t", "web_url": "u", "state": "merged", "source_branch": "b"},
    )

    assert main(["clean", "--merged", "--dry-run"]) == 0

    out = capsys.readouterr().out
    assert out.index("!999") < out.index("!1235")


def test_clean_skips_mr_whose_state_lookup_fails(
    git_repo, commit, checkout, glab, monkeypatch, capsys
):
    # 가짜 glab 은 등록되지 않은 경로에서 exit 1 이다 (testing.md §2) — 네트워크
    # 장애를 흉내 내는 데 새 하네스 기능이 필요 없다. 1234 는 라우트를 등록하지
    # 않아 상태 조회가 실패하고, 1235 는 정상 응답으로 제거된다. 하나가
    # 실패해도 전체 명령이 죽지 않아야 한다.
    commit({"src/api/client.py": "x\n"})
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    _place(git_repo, 1234)
    _place(git_repo, 1235)
    glab.route(
        "GET projects/:fullpath/merge_requests/1235",
        {"iid": 1235, "title": "t", "web_url": "u", "state": "merged", "source_branch": "b"},
    )

    assert main(["clean", "--merged"]) == 0

    assert store.review_dir(git_repo, 1234).exists()
    assert not store.review_dir(git_repo, 1235).exists()
    assert "1234" in capsys.readouterr().err
