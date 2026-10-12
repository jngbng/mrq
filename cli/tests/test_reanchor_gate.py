"""품질 회귀 게이트. docs/spec/reanchoring.md §8.

선행 지표에 테스트를 걸어 알고리즘 튜닝이 조용히 퇴보하지 않게 한다. 목표는
exact >= 75%, stale <= 10% 이며, 코퍼스는 exact 17 / fuzzy 3 / stale 1 이 나오게
구성되어 있다. rename 은 이 브랜치에서 두 번 재발한 결함 종류라 코퍼스에도
반드시 있어야 한다.
"""

import subprocess

from mrq import anchor as anchor_mod
from mrq import model, reanchor
from tests.test_reanchor import make_review, make_thread

BODY = "def f{n}():\n    before{n}()\n    target{n}()\n    after{n}()\n"


def build_corpus(git_repo, commit):
    files = {}
    for index in range(1, 21):
        files[f"m{index}.py"] = BODY.format(n=index)
    files["m21.py"] = BODY.format(n=21)  # rename 전용. 아래에서 옮긴다.
    sha = commit(files)

    for index in range(1, 17):  # exact: 앵커 줄 위에 삽입
        path = git_repo / f"m{index}.py"
        path.write_text("INSERTED\n" + BODY.format(n=index), encoding="utf-8")
    for index in range(17, 20):  # fuzzy: 인덴트만 변경
        path = git_repo / f"m{index}.py"
        path.write_text(
            BODY.format(n=index).replace(f"    target{index}()", f"        target{index}()"),
            encoding="utf-8",
        )
    path = git_repo / "m20.py"  # stale: 앵커 줄 삭제
    path.write_text(BODY.format(n=20).replace("    target20()\n", ""), encoding="utf-8")
    # exact: 파일 rename. git 매핑이 경로를 따라가는지가 게이트에서 빠져
    # 있었다 — 이 결함 종류가 이 브랜치에서 이미 두 번 재발했다.
    subprocess.run(["git", "mv", "m21.py", "m21_renamed.py"], cwd=git_repo, check=True)

    refs = model.DiffRefs(sha, sha, sha)
    threads = []
    for index in range(1, 21):
        position = model.Position("text", f"m{index}.py", f"m{index}.py", None, 3, None)
        thread = make_thread(position, anchor_mod.extract(git_repo, refs, position))
        thread.id = f"t{index}"
        threads.append(thread)
    rename_position = model.Position("text", "m21.py", "m21.py", None, 3, None)
    rename_thread = make_thread(
        rename_position, anchor_mod.extract(git_repo, refs, rename_position)
    )
    rename_thread.id = "t21"
    threads.append(rename_thread)
    return make_review(refs, threads)


def test_quality_gate(git_repo, commit):
    review = build_corpus(git_repo, commit)
    stats = reanchor.reanchor_all(git_repo, review)
    total = stats.exact + stats.fuzzy + stats.stale
    assert total == 21
    assert stats.exact / total >= 0.75, stats
    assert stats.stale / total <= 0.10, stats
    renamed = next(t for t in review.threads if t.id == "t21")
    assert renamed.location.path == "m21_renamed.py"
    assert (renamed.location.confidence, renamed.location.method) == ("exact", "git-diff")


def test_corpus_composition_is_as_designed(git_repo, commit):
    # 구성이 바뀌면 게이트의 의미도 바뀐다. 의도를 고정한다.
    review = build_corpus(git_repo, commit)
    stats = reanchor.reanchor_all(git_repo, review)
    assert stats.as_dict() == {"exact": 17, "fuzzy": 3, "stale": 1}
