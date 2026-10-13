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
    # 9개 discussion 중 system 전용 1개(00ff00ff00ff)가 빠진다.
    assert len(review.threads) == 8


def test_pull_prints_summary(pullable, capsys):
    main(["pull"])
    out = capsys.readouterr().out
    assert "!1234" in out
    assert "reanchored:" in out
    assert "exact" in out
    # 픽스처에는 서버에서 이미 resolve 된 스레드가 하나(33445566ccdd) 있다.
    # 그 숫자를 len(threads) 로 바꿔치기해도 테스트가 통과하면 안 된다 —
    # unresolved 는 threads 와 달라야 그 치환을 잡을 수 있다.
    assert "threads 8" in out
    assert "unresolved 7" in out


def test_pull_locates_diff_comment_in_worktree(pullable):
    main(["pull"])
    review = read_review(pullable)
    thread = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    assert thread.location.path == "src/api/client.py"
    assert thread.location.line == 3
    assert thread.location.confidence == "exact"


def test_pull_spans_multiline_range_regardless_of_new_line_side(pullable):
    # 픽스처에 같은 범위(2~3)를 가리키는 두 모양이 있다 — new_line 이 범위의
    # 시작인 것(11223344aabb)과 끝인 것(55667788eeff). GitLab 이 보낸 값을
    # 정규화하지 않으므로 둘 다 들어온다 (MR !1 실측).
    main(["pull"])
    review = read_review(pullable)
    at_start = next(t for t in review.threads if t.id == "11223344aabb")
    at_end = next(t for t in review.threads if t.id == "55667788eeff")

    for thread in (at_start, at_end):
        assert (thread.location.line, thread.location.line_end) == (2, 3)
        assert thread.location.confidence == "exact"
        # 앵커는 끝 줄이 아니라 시작 줄의 내용이다.
        assert thread.anchor.line == "    session = make_session()"


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


def test_pull_writes_mrq_gitignore(pullable):
    main(["pull"])
    text = (pullable / ".mrq" / ".gitignore").read_text(encoding="utf-8")
    assert "*" in text.splitlines()


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


def test_pull_renders_md_by_default(pullable):
    assert main(["pull"]) == 0
    text = store.review_md_path(pullable, 1234).read_text(encoding="utf-8")
    assert text.startswith("<!-- mrq:file schema=1 iid=1234 head=")
    assert read_review(pullable).rendered_at is not None


def test_pull_no_render_leaves_md_absent_and_rendered_at_null(pullable):
    # 처음부터 md 가 없었던 경우 — 이어받을 값도 없으므로 null 이다.
    assert main(["pull", "--no-render"]) == 0
    assert not store.review_md_path(pullable, 1234).exists()
    assert read_review(pullable).rendered_at is None


def test_pull_no_render_keeps_the_existing_rendered_at(pullable):
    # md 가 디스크에 그대로 있는데 `rendered_at` 만 null 로 돌아가면
    # `status` 가 `synced -` 를 찍어 편집면이 없는 것처럼 보인다.
    assert main(["pull"]) == 0
    rendered_at = read_review(pullable).rendered_at
    assert rendered_at is not None

    assert main(["pull", "--no-render"]) == 0

    assert store.review_md_path(pullable, 1234).is_file()  # md 는 그대로다
    assert read_review(pullable).rendered_at == rendered_at


def test_pull_render_only_touches_no_network(pullable, glab):
    assert main(["pull"]) == 0
    store.review_md_path(pullable, 1234).unlink()
    before = len(glab.calls())

    assert main(["pull", "--render"]) == 0

    assert len(glab.calls()) == before
    assert store.review_md_path(pullable, 1234).is_file()


def test_pull_render_all_includes_server_resolved_threads(pullable):
    assert main(["pull"]) == 0
    default_md = store.review_md_path(pullable, 1234).read_text(encoding="utf-8")
    assert main(["pull", "--render", "--all"]) == 0
    all_md = store.review_md_path(pullable, 1234).read_text(encoding="utf-8")
    assert all_md.count("<!-- mrq:") > default_md.count("<!-- mrq:")


def test_pull_render_without_state_guides_to_pull(git_repo, commit, monkeypatch):
    commit({"a.py": "x\n"})
    monkeypatch.chdir(git_repo)
    assert main(["pull", "--render"]) == 1


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
    assert json.loads(out) == {"anchors": {"exact": 5, "fuzzy": 0, "stale": 0}}


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


def test_pull_recovers_from_older_schema_version(pullable, capsys):
    assert main(["pull"]) == 0
    path = store.review_json_path(pullable, 1234)
    text = path.read_text(encoding="utf-8")
    text = text.replace('"schema_version": 1', '"schema_version": 0', 1)
    text = text.replace('"reply": ""', '"reply": "전송 전 답글"', 1)
    path.write_text(text, encoding="utf-8")

    assert main(["pull"]) == 0
    review = read_review(pullable)
    assert any(t.local.reply == "전송 전 답글" for t in review.threads)
    assert "schema_version" in capsys.readouterr().err


def test_pull_refuses_newer_schema_version(pullable):
    assert main(["pull"]) == 0
    path = store.review_json_path(pullable, 1234)
    path.write_text(
        path.read_text(encoding="utf-8").replace('"schema_version": 1', '"schema_version": 99', 1),
        encoding="utf-8",
    )
    assert main(["pull"]) == 7


def test_pull_recovers_from_corrupt_json(pullable, capsys):
    assert main(["pull"]) == 0
    store.review_json_path(pullable, 1234).write_text("{not json", encoding="utf-8")
    assert main(["pull"]) == 0
    assert len(read_review(pullable).threads) == 8


def test_pull_recovers_from_malformed_push_error(pullable, capsys):
    assert main(["pull"]) == 0
    path = store.review_json_path(pullable, 1234)
    text = path.read_text(encoding="utf-8")
    text = text.replace('"push_error": null', '"push_error": {"bogus": "shape"}', 1)
    path.write_text(text, encoding="utf-8")

    # dumps 가 검증 실패를 감싸지 않으므로, 살려낸 push_error 가 스키마를
    # 어긴 채로 넘어가면 여기서 트레이스백으로 죽는다 (exit 0 이 아니게 된다).
    assert main(["pull"]) == 0
    assert "push_error" in capsys.readouterr().err
