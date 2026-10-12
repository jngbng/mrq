import pytest

from mrq import threads
from mrq.errors import UsageError
from tests.test_render import thread as make_thread


class _R:
    def __init__(self, threads_list):
        self.threads = threads_list


def test_resolve_ref_matches_exact_id():
    review = _R([make_thread(id="a1b2c3d4e5f6"), make_thread(id="b2c3d4e5f6a1")])
    assert threads.resolve_ref(review, "a1b2c3d4e5f6").id == "a1b2c3d4e5f6"


def test_resolve_ref_matches_unique_prefix():
    review = _R([make_thread(id="a1b2c3d4e5f6"), make_thread(id="b2c3d4e5f6a1")])
    assert threads.resolve_ref(review, "a1b2").id == "a1b2c3d4e5f6"


def test_resolve_ref_raises_on_unknown_prefix():
    review = _R([make_thread(id="a1b2c3d4e5f6")])
    with pytest.raises(UsageError, match="mrq list"):
        threads.resolve_ref(review, "zzzz")


def test_resolve_ref_raises_on_ambiguous_prefix_and_lists_candidates():
    review = _R(
        [
            make_thread(id="a1b2c3d4e5f6", author="jdoe"),
            make_thread(id="a1b2ffffffff", author="kim"),
        ]
    )
    with pytest.raises(UsageError) as excinfo:
        threads.resolve_ref(review, "a1b2")
    message = str(excinfo.value)
    assert "a1b2c3d4e5f6" in message
    assert "a1b2ffffffff" in message
    assert "@jdoe" in message
    assert "@kim" in message


def test_resolve_ref_rejects_empty_string():
    # 빈 문자열은 모든 id 의 접두사이므로, 스레드가 하나뿐이어도 "유일하게
    # 일치"로 잘못 통과시키면 안 된다 — 사용자가 아무것도 지정하지 않은 것과
    # 같은 취급을 받으면 안 된다.
    review = _R([make_thread(id="a1b2c3d4e5f6")])
    with pytest.raises(UsageError):
        threads.resolve_ref(review, "")
