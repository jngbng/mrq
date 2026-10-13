import json

import pytest

from mrq import model, push, report, store, surface
from mrq.__main__ import main

SAMPLE = model.schema_path().parent.parent / "testdata" / "review" / "rendered.json"


def _review() -> model.Review:
    return model.loads(SAMPLE.read_text(encoding="utf-8"))


def _blank(review: model.Review) -> model.Review:
    """샘플에 섞여 있는 미전송 답글/상태를 비운다 (`test_push.py` 와 같은 이유).

    절대 수를 단언하는 테스트에서만 쓴다 — 다른 테스트는 표본 그대로를 보고
    `>=`/`in` 으로 확인한다.
    """
    for thread in review.threads:
        thread.local.state = "todo"
        thread.local.reply = ""
        thread.local.pushed_hash = None
        thread.local.push_error = None
    return review


@pytest.fixture
def ready(git_repo, commit, checkout, monkeypatch):
    commit({"src/api/client.py": "x\n"})
    # 샘플의 source_branch 와 저장소를 맞춘다 — 안 맞으면 브랜치 가드가 경고
    # (읽기) 또는 exit 1 (쓰기) 을 낸다 (testing.md §5).
    checkout("feat/retry")
    monkeypatch.chdir(git_repo)
    review = _review()
    with store.review_lock(git_repo, review.iid):
        surface.write(git_repo, review, include_resolved=True)
    store.write_current(git_repo, review.iid)
    return git_repo


def test_payload_counts_threads_and_local_states():
    payload = report.status_payload(_review())
    assert payload["iid"] == 1234
    assert payload["threads"]["total"] == 7
    assert payload["threads"]["resolved_on_server"] == 2
    assert payload["threads"]["unresolved"] == 5
    assert sum(payload["local"].values()) == 7
    assert set(payload["local"]) == {"todo", "done", "replied", "skipped"}


def test_payload_excludes_null_location_from_anchor_stats():
    payload = report.status_payload(_review())
    # 스레드 6개 중 location 이 null 인 general 하나는 통계에서 빠진다 (§4.9 MUST).
    assert sum(payload["anchors"].values()) == 6


def test_payload_excludes_server_missing_from_anchor_stats():
    # a1b2c3d4e5f6 는 표본에서 location 이 null 이 아닌 스레드다. server.missing
    # 으로 표시해도 threads/local 집계는 그대로 7 을 세지만 (§4.9 는 anchors 에만
    # 적용된다), anchors 에서는 하나 빠져야 한다 — 사라진 스레드의 위치 품질은
    # "현재 활성 코멘트 재배치" 지표의 모집단이 아니다.
    review = _review()
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.server.missing = True
    payload = report.status_payload(review)
    assert sum(payload["anchors"].values()) == 5
    assert payload["threads"]["total"] == 7
    assert sum(payload["local"].values()) == 7


def test_payload_counts_pending_reply_and_resolve():
    review = _review()
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    target.local.reply = "보낼 답글"
    payload = report.status_payload(review)
    assert payload["push"]["replies"] >= 1
    assert payload["push"]["resolves"] >= 1


def test_payload_warns_without_resolve_permission():
    review = _review()
    review.me.can_resolve = False
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    payload = report.status_payload(review)
    assert payload["push"]["resolves"] == 0
    assert {"thread": None, "reason": "no-resolve-permission"} in payload["warnings"]


def test_payload_never_warns_server_changed_even_when_the_clock_skews():
    # `server-changed` 는 삭제됐다 (`cli.md` §8, `report.py` docstring).
    # `server.*` 는 `pulled_at` 과 같은 스냅샷이 쓰므로 이 판정은 구조적으로
    # 거짓이고, 클라이언트 시계가 뒤처지면 **거짓 참**이 되어 보낼 답글을
    # 검토면에서 지워 버렸다. 그 회귀를 고정한다.
    review = _review()
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    target.local.reply = "보낼 답글"
    target.server.updated_at = "2099-01-01T00:00:00+09:00"  # 시계 꼬임 시뮬레이션

    payload = report.status_payload(review)

    assert all(w["reason"] != "server-changed" for w in payload["warnings"])
    # 이 답글과 resolve 는 여전히 전송 대상으로 세어진다 — 건너뛰지 않는다.
    assert payload["push"]["replies"] == report.status_payload(_review())["push"]["replies"] + 1
    assert payload["push"]["resolves"] >= 1
    assert payload["push"]["skip"] == 0


def test_payload_tolerates_naive_timestamps():
    # 옛 비교는 offset-naive 와 offset-aware 를 맞대 TypeError 로 터졌다.
    # 비교 자체가 없어졌으므로 섞인 타임스탬프도 그냥 지나가야 한다.
    review = _review()
    review.pulled_at = "2026-10-11T09:12:00"
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    target.local.reply = "보낼 답글"
    target.server.updated_at = "2026-10-11T10:00:00"

    payload = report.status_payload(review)
    assert payload["push"]["replies"] >= 1


def test_payload_warns_on_unrepliable_thread_with_reply():
    review = _review()
    target = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")  # repliable: false
    target.local.state = "replied"
    target.local.reply = "전송 못 하는 답글"
    payload = report.status_payload(review)
    assert {"thread": "7a0b1c2d3e4f", "reason": "no-reply"} in payload["warnings"]


def test_payload_warns_on_not_resolvable_thread():
    review = _review()
    # 7a0b1c2d3e4f 는 server.resolvable 이 이미 false 다 (fixture).
    target = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")
    target.local.state = "done"
    payload = report.status_payload(review)
    assert {"thread": "7a0b1c2d3e4f", "reason": "not-resolvable"} in payload["warnings"]


def test_payload_skip_counts_once_for_combined_block_reasons():
    review = _review()
    # 7a0b1c2d3e4f 는 repliable 과 resolvable 이 모두 false 다 — state=done 에
    # reply 까지 채우면 no-reply 와 not-resolvable 이 동시에 걸린다. 그래도
    # skip 은 그 스레드에 대해 한 번만 올라가야 한다.
    target = next(t for t in review.threads if t.id == "7a0b1c2d3e4f")
    target.local.state = "done"
    target.local.reply = "전송도 resolve 도 안 되는 답글"
    payload = report.status_payload(review)
    assert {"thread": "7a0b1c2d3e4f", "reason": "no-reply"} in payload["warnings"]
    assert {"thread": "7a0b1c2d3e4f", "reason": "not-resolvable"} in payload["warnings"]
    # 표본의 다른 스레드들은 이 변경과 무관하게 영향받지 않으므로, 전체 skip 이
    # 정확히 1(이 스레드만)이어야 두 사유가 각각 skip 을 올리지 않았다는 뜻이다.
    assert payload["push"]["skip"] == 1


def test_payload_warns_when_mr_is_not_opened():
    review = _review()
    review.mr_state = "merged"
    payload = report.status_payload(review)
    assert {"thread": None, "reason": "mr-not-opened"} in payload["warnings"]


def test_status_json_is_pure_json(ready, capsys):
    assert main(["status", "--json"]) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["head_sha"] == "abc1234"
    assert payload["rendered_at"] is not None


def test_status_human_output_has_the_review_surface(ready, capsys):
    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "!1234" in out
    assert "threads" in out and "anchors" in out and "push" in out


def test_status_without_state_exits_1(git_repo, commit, monkeypatch):
    commit({"a.py": "x\n"})
    monkeypatch.chdir(git_repo)
    assert main(["status"]) == 1


def test_status_without_md_guides_to_pull_render_and_keeps_exit_zero(ready, capsys):
    # data-model.md §1 "손실 복구" — md 부재는 sync/status/push 가 모두
    # 안내해야 한다(MUST). json 이 정본이므로 exit 0 이다.
    store.review_md_path(ready, 1234).unlink()
    assert main(["status"]) == 0
    err = capsys.readouterr().err
    assert "review.md 가 없습니다" in err and "mrq pull --render" in err
    assert "review.json 은 온전합니다" in err


def test_status_json_stays_pure_json_without_md(ready, capsys):
    store.review_md_path(ready, 1234).unlink()
    assert main(["status", "--json"]) == 0
    captured = capsys.readouterr()
    assert json.loads(captured.out)["iid"] == 1234  # stdout 에 경고가 섞이지 않는다
    assert "mrq pull --render" in captured.err


def test_status_warns_but_still_reports_after_the_checkout_moved(ready, checkout, capsys):
    # testing.md §5 — "pull 후 브랜치 변경 → status". 읽기 경로는 끊지 않는다.
    checkout("feat/other")
    assert main(["status"]) == 0
    captured = capsys.readouterr()
    assert "!1234" in captured.out
    assert "feat/other" in captured.err and "feat/retry" in captured.err
    assert "mrq pull" in captured.err


def test_status_does_not_warn_in_detached_head_as_if_the_branch_moved(ready, capsys):
    # detached HEAD 는 "다른 MR 의 브랜치" 가 아니다 — 비교할 이름이 없다고
    # 말할 뿐이고, 쓰기를 막지도 않는다 (store.check_branch 참조).
    import subprocess

    sha = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=ready, capture_output=True, text=True, check=True
    ).stdout.strip()
    subprocess.run(["git", "checkout", "-q", "--detach", sha], cwd=ready, check=True)

    assert main(["status"]) == 0
    err = capsys.readouterr().err
    assert "detached HEAD" in err
    assert "mrq pull" not in err


def test_status_push_block_matches_plan_without_snapshot():
    review = _review()
    target = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    target.local.state = "done"
    target.local.reply = "보낼 답글"

    payload = report.status_payload(review)
    sheet = push.plan(review)

    assert payload["push"] == {
        "replies": sheet.replies,
        "resolves": sheet.resolves,
        "skip": sheet.skip,
    }
    assert payload["warnings"] == sheet.warnings


def test_status_warns_about_missing_thread_and_recorded_failure(ready, capsys):
    # 표본의 다른 두 스레드(c3d4e5f6a1b2, d4e5f6a1b2c3)에도 미전송 답글이
    # 있으므로, 절대 수(`replies == 0`)를 보려면 비워야 한다 — 그 두 스레드는
    # 이 테스트와 무관하다.
    review = _blank(_review())
    missing = next(t for t in review.threads if t.id == "a1b2c3d4e5f6")
    missing.local.state = "done"
    missing.local.reply = "보낼 답글"
    missing.server.missing = True

    payload = report.status_payload(review)

    assert {"thread": "a1b2c3d4e5f6", "reason": "server-missing"} in payload["warnings"]
    assert payload["push"]["replies"] == 0
    assert payload["push"]["skip"] == 1

    # Minor 11 — testing.md §5 "resolve 403 이 기록된 뒤 status | push-failed
    # 경고가 보인다" 행은 이 이름의 테스트가 지금까지 push_error 를 전혀
    # 설정하지 않아 실제로는 검증하지 않았다. push_error 가 json 안에만
    # 남지 않고(cli.md §9) `mrq status` 의 렌더된 화면에도 보이는지 끝까지
    # 확인한다.
    failed = next(t for t in review.threads if t.id == "b2c3d4e5f6a1")
    failed.local.push_error = {
        "op": "resolve",
        "status": 403,
        "reason": "forbidden",
        "retryable": False,
        "at": "2026-10-13T10:02:00+09:00",
        "message": "403 Forbidden",
    }
    with store.review_lock(ready, review.iid):
        surface.write(ready, review, include_resolved=True)

    assert main(["status"]) == 0
    out = capsys.readouterr().out
    assert "b2c3d4e5f6a1"[:8] in out
    assert "지난 전송이 실패했습니다" in out
