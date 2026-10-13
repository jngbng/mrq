import json
import os
import subprocess
import time
from pathlib import Path

import pytest

from mrq import model, store


@pytest.fixture(scope="session", autouse=True)
def pinned_timezone():
    """렌더 시각은 로컬 타임존으로 변환된다 (`docs/spec/review-md.md` §5).

    그래서 골든의 결정성을 머신 설정에 맡길 수 없다. 여기서 고정한다 —
    UTC 로 고정하면 변환이 일어나는지 아닌지를 구분하지 못하므로 안 된다.
    """
    os.environ["TZ"] = "Asia/Seoul"
    time.tzset()


def _git(repo: Path, *args: str) -> str:
    return subprocess.run(
        ["git", *args], cwd=repo, capture_output=True, text=True, check=True
    ).stdout


@pytest.fixture
def git_repo(tmp_path: Path) -> Path:
    """실제 git 저장소. git 을 모킹하지 않는다 (Global Constraints)."""
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    _git(repo, "config", "user.email", "t@example.com")
    _git(repo, "config", "user.name", "tester")
    _git(repo, "config", "commit.gpgsign", "false")
    return repo


@pytest.fixture
def commit(git_repo: Path):
    """파일들을 쓰고 커밋한 뒤 sha 를 돌려준다."""

    def _commit(files: dict[str, str], message: str = "c") -> str:
        for rel, text in files.items():
            path = git_repo / rel
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")
        _git(git_repo, "add", "-A")
        _git(git_repo, "commit", "-q", "-m", message)
        return _git(git_repo, "rev-parse", "HEAD").strip()

    return _commit


@pytest.fixture
def checkout(git_repo: Path):
    """브랜치를 만들어 체크아웃한다.

    샘플 `review.json` 의 `source_branch`(`feat/retry`)와 저장소를 맞추는 데 쓴다 —
    명령들이 브랜치 가드를 통과해야 한다 (`docs/spec/testing.md` §5).
    """

    def _checkout(branch: str, *, new: bool = True) -> None:
        _git(git_repo, "checkout", "-q", *(["-b"] if new else []), branch)

    return _checkout


@pytest.fixture
def glab(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """가짜 glab 을 PATH 앞에 꽂는다. subprocess 를 모킹하지 않는다."""
    fixtures = tmp_path / "glab-fixtures"
    fixtures.mkdir()
    log = tmp_path / "glab.log"
    monkeypatch.setenv("MRQ_GLAB_FIXTURES", str(fixtures))
    monkeypatch.setenv("MRQ_GLAB_LOG", str(log))
    monkeypatch.setenv("PATH", f"{Path(__file__).parent / 'bin'}{os.pathsep}{os.environ['PATH']}")

    class Harness:
        def __init__(self) -> None:
            self.routes: dict[str, str] = {}

        def route(self, key: str, payload=None, *, raw: str | None = None) -> None:
            """`"GET projects/:fullpath/user"` 같은 키에 응답을 등록한다."""
            name = f"r{len(self.routes)}.json"
            text = raw if raw is not None else json.dumps(payload, ensure_ascii=False)
            (fixtures / name).write_text(text, encoding="utf-8")
            self.routes[key] = name
            (fixtures / "routes.json").write_text(
                json.dumps(self.routes, ensure_ascii=False), encoding="utf-8"
            )

        def fail_at(self, *indices: int) -> None:
            monkeypatch.setenv("MRQ_GLAB_FAIL_AT", ",".join(str(i) for i in indices))

        def calls(self) -> list[dict]:
            if not log.exists():
                return []
            return [json.loads(line) for line in log.read_text(encoding="utf-8").splitlines()]

    return Harness()


@pytest.fixture
def review_json():
    """최소 review.json 을 `.mrq/<iid>/` 에 써 둔다."""

    def _write(root: Path, *, iid: int, source_branch: str, threads=None) -> Path:
        review = model.Review(
            schema_version=model.SCHEMA_VERSION,
            project="group/sub/project",
            iid=iid,
            title="t",
            web_url=f"https://gitlab.example.com/g/p/-/merge_requests/{iid}",
            mr_state="opened",
            source_branch=source_branch,
            diff_refs=model.DiffRefs("0000aaa", "0000bbb", "abc1234"),
            me=model.Me(id=7, username="bongya", can_resolve=True),
            capabilities=model.Capabilities(draft_notes=True),
            pulled_at="2026-10-11T09:12:00+09:00",
            rendered_at=None,
            threads=threads or [],
        )
        path = store.review_json_path(root, iid)
        store.atomic_write_text(path, model.dumps(review))
        return path

    return _write
