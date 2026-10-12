import json
import subprocess
from pathlib import Path

import pytest

from mrq import model, store
from mrq.__main__ import main

FIXTURES = Path(__file__).parent / "fixtures"
CLIENT = "def fetch(url):\n    session = make_session()\n    resp = session.get(url)\n"

MR = {
    "iid": 1234,
    "title": "Add retry logic to API client",
    "web_url": "https://gitlab.example.com/g/p/-/merge_requests/1234",
    "state": "opened",
    "source_branch": "feat/retry",
}
SEARCH = "GET projects/:fullpath/merge_requests?source_branch=feat/retry&state=opened&per_page=100"


@pytest.fixture
def pullable(git_repo, commit, glab, monkeypatch):
    """브랜치, 파일, glab 응답을 모두 갖춘 상태."""
    sha = commit({"src/api/client.py": CLIENT, "docs/screen.png": "fake\n"})
    subprocess.run(["git", "checkout", "-q", "-b", "feat/retry"], cwd=git_repo, check=True)
    monkeypatch.chdir(git_repo)

    glab.route(SEARCH, [MR])
    # 두 번째 pull 은 current 포인터를 재사용해 단일 MR 조회로 간다.
    glab.route("GET projects/:fullpath/merge_requests/1234", MR)
    glab.route(
        "GET projects/:fullpath",
        {
            "path_with_namespace": "group/sub/project",
            "permissions": {"project_access": {"access_level": 40}, "group_access": None},
        },
    )
    glab.route("GET user", {"id": 7, "username": "bongya"})
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [{"head_commit_sha": sha, "base_commit_sha": sha, "start_commit_sha": sha}],
    )
    glab.route("GET projects/:fullpath/merge_requests/1234/draft_notes", [])
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        raw=(FIXTURES / "discussions.ndjson").read_text(encoding="utf-8"),
    )
    return git_repo


def read_review(root: Path, iid: int = 1234) -> model.Review:
    return model.loads(store.review_json_path(root, iid).read_text(encoding="utf-8"))


def test_pull_writes_validated_review_json(pullable, capsys):
    assert main(["pull"]) == 0
    review = read_review(pullable)
    assert review.iid == 1234
    assert review.project == "group/sub/project"
    assert review.me.can_resolve is True
    assert review.capabilities.draft_notes is True
    # 8개 discussion 중 system 전용 1개(00ff00ff00ff)가 빠진다.
    assert len(review.threads) == 7


def test_pull_prints_summary(pullable, capsys):
    main(["pull"])
    out = capsys.readouterr().out
    assert "!1234" in out
    assert "reanchored:" in out
    assert "exact" in out
    # 픽스처에는 서버에서 이미 resolve 된 스레드가 하나(33445566ccdd) 있다.
    # 그 숫자를 len(threads) 로 바꿔치기해도 테스트가 통과하면 안 된다 —
    # unresolved 는 threads 와 달라야 그 치환을 잡을 수 있다.
    assert "threads 7" in out
    assert "unresolved 6" in out


def test_pull_locates_diff_comment_in_worktree(pullable):
    main(["pull"])
    review = read_review(pullable)
    thread = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    assert thread.location.path == "src/api/client.py"
    assert thread.location.line == 3
    assert thread.location.confidence == "exact"


def test_pull_gives_null_location_to_general_and_image(pullable):
    main(["pull"])
    review = read_review(pullable)
    general = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")
    image = next(t for t in review.threads if t.id == "ffee1122aabb")
    assert general.location is None
    assert image.location is None


def test_pull_marks_individual_note_not_repliable(pullable):
    main(["pull"])
    review = read_review(pullable)
    general = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")
    assert general.server.repliable is False


def test_pull_registers_git_exclude(pullable):
    main(["pull"])
    exclude = (pullable / ".git" / "info" / "exclude").read_text(encoding="utf-8")
    assert "/.mrq/" in exclude


def test_pull_writes_current_pointer(pullable):
    main(["pull"])
    assert store.read_current(pullable) == 1234
    assert (pullable / ".mrq" / "current" / "review.json").is_file()


def test_pull_preserves_local_state(pullable):
    main(["pull"])
    path = store.review_json_path(pullable, 1234)
    review = read_review(pullable)
    thread = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    thread.local.state = "done"
    thread.local.reply = "확인했습니다."
    thread.local.pushed_hash = "deadbeef"
    store.atomic_write_text(path, model.dumps(review))

    main(["pull"])
    again = next(t for t in read_review(pullable).threads if t.id == "a1b2c3d4e5f6")
    assert (again.local.state, again.local.reply) == ("done", "확인했습니다.")
    assert again.local.pushed_hash == "deadbeef"


def test_pull_drops_threads_removed_on_server(pullable, glab):
    main(["pull"])
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/discussions",
        raw=(FIXTURES / "discussions.ndjson").read_text(encoding="utf-8").splitlines()[0] + "\n",
    )
    main(["pull"])
    assert [t.id for t in read_review(pullable).threads] == ["a1b2c3d4e5f6"]


def test_pull_keeps_previous_anchor_when_head_unavailable(pullable, glab):
    # head_sha 를 로컬에서 확보할 수 없으면 git show 가 모든 스레드에서
    # 실패해 anchor.extract 가 None 을 돌려준다. FIX 2 이전 코드는 그 None 을
    # 그대로 덮어써 anchor 가 사라졌고, _locate 는 anchor 가 없으면 무조건
    # stale 이라 reanchor 로도 복구할 길이 없었다.
    #
    # pull 은 diff_refs 를 매번 서버(versions 엔드포인트)에서 새로 받으므로
    # review.json 을 직접 고쳐도 소용없다 — 두 번째 pull 에서 versions 라우트
    # 자체를 리포에 없는 sha 로 재등록해야 한다. origin 리모트가 없는 테스트
    # 저장소라 fetch 는 즉시 실패하고 have_git=False 로 떨어진다.
    main(["pull"])
    before = next(t for t in read_review(pullable).threads if t.id == "a1b2c3d4e5f6")
    assert before.anchor is not None

    missing_sha = "b" * 40  # 리포에 존재하지 않는 객체.
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [
            {
                "head_commit_sha": missing_sha,
                "base_commit_sha": missing_sha,
                "start_commit_sha": missing_sha,
            }
        ],
    )

    main(["pull"])
    after = next(t for t in read_review(pullable).threads if t.id == "a1b2c3d4e5f6")
    assert after.anchor is not None
    assert after.anchor == before.anchor
    assert after.location.confidence != "stale"


def test_pull_render_is_not_implemented_yet(pullable, capsys):
    assert main(["pull", "--render"]) == 1
    assert "렌더러" in capsys.readouterr().err


def test_reanchor_requires_pull_first(git_repo, commit, monkeypatch, capsys):
    commit({"a.py": "x\n"})
    monkeypatch.chdir(git_repo)
    assert main(["reanchor"]) == 1
    assert "mrq pull" in capsys.readouterr().err


def test_reanchor_updates_location_after_edit(pullable, capsys):
    main(["pull"])
    (pullable / "src" / "api" / "client.py").write_text(
        "HEADER1\nHEADER2\n" + CLIENT, encoding="utf-8"
    )
    capsys.readouterr()
    assert main(["reanchor"]) == 0
    thread = next(t for t in read_review(pullable).threads if t.id == "a1b2c3d4e5f6")
    assert thread.location.line == 5


def test_reanchor_json_emits_only_json_on_stdout(pullable, capsys):
    main(["pull"])
    capsys.readouterr()
    assert main(["reanchor", "--json"]) == 0
    out = capsys.readouterr().out
    # 텍스트 position 을 가진 스레드 4개(a1b2c3d4e5f6, 11223344aabb,
    # 22334455bbcc, 33445566ccdd) 모두 작업 트리를 건드리지 않았으므로 exact다.
    assert json.loads(out) == {"anchors": {"exact": 4, "fuzzy": 0, "stale": 0}}


def test_reanchor_never_fetches(pullable, monkeypatch, capsys):
    """reanchor 는 네트워크를 쓰지 않는다 (docs/spec/cli.md §6).

    pull 로 받은 review.json 의 diff_refs 를 리포에 없는 sha 로 바꿔 커밋이
    없는 상태를 만든다. ensure_commits 가 여전히 fetch 를 시도하면 가짜
    gitcmd.fetch 가 즉시 AssertionError 를 던지므로 — 오프라인에서 수 분을
    먹는 실제 TCP 타임아웃 대신 테스트에서 즉시 드러난다.
    """
    main(["pull"])
    path = store.review_json_path(pullable, 1234)
    review = read_review(pullable)
    missing_sha = "a" * 40  # 리포에 존재하지 않는 객체.
    review.diff_refs.head_sha = missing_sha
    review.diff_refs.start_sha = missing_sha
    store.atomic_write_text(path, model.dumps(review))

    def boom(root, refspec):
        raise AssertionError("reanchor must not fetch")

    monkeypatch.setattr("mrq.gitcmd.fetch", boom)
    capsys.readouterr()
    assert main(["reanchor"]) == 0
