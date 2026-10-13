import pytest

from mrq import mr, store
from mrq.errors import GlabError, MrDetectionError

MR_1234 = {
    "iid": 1234,
    "title": "Add retry logic to API client",
    "web_url": "https://gitlab.example.com/g/p/-/merge_requests/1234",
    "state": "opened",
    "source_branch": "feat/retry",
}
MR_5678 = {**MR_1234, "iid": 5678, "title": "Other", "source_branch": "feat/retry"}

SEARCH = "GET projects/:fullpath/merge_requests"


@pytest.fixture
def repo_on_branch(git_repo, commit):
    commit({"a.py": "x\n"})
    import subprocess

    subprocess.run(["git", "checkout", "-q", "-b", "feat/retry"], cwd=git_repo, check=True)
    return git_repo


def test_detect_single_mr(repo_on_branch, glab):
    glab.route(SEARCH, [MR_1234])
    info = mr.detect(repo_on_branch)
    assert (info.iid, info.source_branch, info.mr_state) == (1234, "feat/retry", "opened")


def test_detect_zero_mrs(repo_on_branch, glab):
    glab.route(SEARCH, [])
    with pytest.raises(MrDetectionError) as excinfo:
        mr.detect(repo_on_branch)
    assert excinfo.value.exit_code == 6
    assert "--mr" in str(excinfo.value)


def test_detect_multiple_mrs_lists_candidates(repo_on_branch, glab):
    glab.route(SEARCH, [MR_1234, MR_5678])
    with pytest.raises(MrDetectionError) as excinfo:
        mr.detect(repo_on_branch)
    assert excinfo.value.exit_code == 6
    assert "!1234" in str(excinfo.value)
    assert "!5678" in str(excinfo.value)


def test_explicit_iid_skips_search(repo_on_branch, glab):
    glab.route("GET projects/:fullpath/merge_requests/1234", MR_1234)
    assert mr.detect(repo_on_branch, explicit_iid=1234).iid == 1234
    assert all(
        not any(arg.startswith("source_branch=") for arg in call["argv"]) for call in glab.calls()
    )


def test_current_is_reused_when_branch_matches(repo_on_branch, glab, review_json):
    review_json(repo_on_branch, iid=1234, source_branch="feat/retry")
    store.write_current(repo_on_branch, 1234)
    glab.route("GET projects/:fullpath/merge_requests/1234", MR_1234)
    assert mr.detect(repo_on_branch).iid == 1234


def test_current_is_ignored_when_branch_differs(repo_on_branch, glab, review_json):
    # 브랜치를 바꿨는데 current 를 그대로 쓰면 다른 MR 의 상태를 보게 된다.
    review_json(repo_on_branch, iid=9999, source_branch="feat/other")
    store.write_current(repo_on_branch, 9999)
    glab.route(SEARCH, [MR_1234])
    assert mr.detect(repo_on_branch).iid == 1234


def test_diff_refs_uses_first_version(glab):
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/versions",
        [
            {
                "head_commit_sha": "abc1234",
                "base_commit_sha": "0000aaa",
                "start_commit_sha": "0000bbb",
            },
            {"head_commit_sha": "old", "base_commit_sha": "o", "start_commit_sha": "o"},
        ],
    )
    refs = mr.diff_refs(1234)
    assert (refs.head_sha, refs.base_sha, refs.start_sha) == ("abc1234", "0000aaa", "0000bbb")


@pytest.mark.parametrize(
    ("permissions", "expected"),
    [
        ({"project_access": {"access_level": 40}, "group_access": None}, True),
        ({"project_access": {"access_level": 30}, "group_access": None}, True),
        ({"project_access": {"access_level": 20}, "group_access": None}, False),
        # 그룹 상속 권한이 프로젝트 권한보다 높을 수 있다.
        ({"project_access": {"access_level": 20}, "group_access": {"access_level": 40}}, True),
        ({"project_access": None, "group_access": None}, False),
    ],
)
def test_can_resolve_from_access_level(glab, permissions, expected):
    glab.route(
        "GET projects/:fullpath",
        {"path_with_namespace": "group/sub/project", "permissions": permissions},
    )
    path, can_resolve = mr.project_info()
    assert path == "group/sub/project"
    assert can_resolve is expected


def test_whoami(glab):
    glab.route("GET user", {"id": 7, "username": "bongya"})
    assert mr.whoami() == (7, "bongya")


def test_draft_notes_available_is_true(glab):
    glab.route("GET projects/:fullpath/merge_requests/1234/draft_notes", [])
    assert mr.draft_notes_available(1234) is True


def test_draft_notes_unavailable_on_404(glab):
    # 이 GitLab 이 draft notes 를 지원하지 않는 경우 — 유일하게 "미지원"으로
    # 확정할 수 있는 상태다.
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/draft_notes",
        {"message": "404 Not found"},
        status=404,
    )
    assert mr.draft_notes_available(1234) is False


def test_draft_notes_raises_on_server_error(glab):
    # Important 4 — 502 같은 일시적 실패를 404(미지원)와 똑같이 `False` 로
    # 접으면 "이 GitLab 은 draft_notes 를 지원하지 않는다" 는 틀린 결론이
    # 영구히 기록된다(`pull` 이 그 값을 `capabilities.draft_notes` 로 쓴다).
    # 404 가 아닌 실패는 호출자(`pull`/`doctor`)에게 그대로 올려 "확인 불가"
    # 와 "미지원"을 구분하게 한다.
    glab.route(
        "GET projects/:fullpath/merge_requests/1234/draft_notes",
        {"message": "502 Bad Gateway"},
        status=502,
    )
    with pytest.raises(GlabError) as excinfo:
        mr.draft_notes_available(1234)
    assert excinfo.value.status == 502


def test_draft_notes_raises_on_network_failure(glab):
    # 라우트가 전혀 등록되지 않은 경우(가짜 glab 의 "등록되지 않은 경로")도
    # status 가 없는 네트워크 실패와 같은 모양이다 — 404 가 아니므로 역시
    # 올려야 한다.
    with pytest.raises(GlabError) as excinfo:
        mr.draft_notes_available(1234)
    assert excinfo.value.status is None


def test_detect_handles_special_characters_in_branch_name(git_repo, commit, glab):
    import subprocess

    commit({"a.py": "x\n"})
    branch = "feat/#123&x%y+z"
    subprocess.run(["git", "checkout", "-q", "-b", branch], cwd=git_repo, check=True)
    glab.route("GET projects/:fullpath/merge_requests", [{**MR_1234, "source_branch": branch}])

    info = mr.detect(git_repo)

    assert info.iid == 1234
    # 쿼리가 경로에 보간되지 않았다. 보간하면 `#` 뒤가 잘려 state 와 per_page
    # 까지 사라지고 닫힌 MR 이 후보에 들어온다.
    argv = glab.calls()[0]["argv"]
    assert argv[1] == "projects/:fullpath/merge_requests"
    assert f"source_branch={branch}" in argv
    assert "state=opened" in argv
