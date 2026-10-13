# 설계 — `glab.api` 상태 코드와 가짜 `glab` 하네스 (R3 · R4)

계획 3의 전 과제 중 남은 둘. 브랜치 `jbseo/pre_step3`에서 R6·R7에 이어 수행한다.
구현 계획은 이 문서가 승인된 뒤 별도로 쓴다.

## 1. 목적

**`push`를 쓰는 것이 아니라 `push`를 TDD로 쓸 수 있게 만든다.** 끝났을 때 다음
둘이 성립해야 한다.

1. `local.push_error.status`에 403·404·네트워크 장애가 **서로 다른 값**으로 들어갈
   수 있다 (`data-model.md` §4.8). 지금은 `api()`가 성공 시 JSON, 실패 시
   `NetworkError`(또는 `check=False`면 `None`)만 주므로 셋을 구분할 수 없다.
2. `testing.md` §6의 다섯 시나리오(멱등성·크래시 복구)를 가짜 `glab`으로 **쓸 수
   있다**. 지금 하네스는 `"<METHOD> <path>"` 키마다 응답 파일 **하나**를 매핑하므로
   호출별 다른 응답도, HTTP 상태 코드도, 2페이지 응답도 표현하지 못한다.

덤으로 브랜치 이름 버그가 닫힌다 (§3).

이 둘을 계획 3에 통합하지 않는 이유는 `docs/plans/README.md`에 적혀 있다 — 계획 3
안에 넣으면 멱등성·크래시 복구를 TDD로 쓸 수 없고 "구현 먼저, 테스트는 하네스를
고친 뒤"가 된다.

## 2. 실측 (glab 1.114.0, 2026-10-13)

설계가 이 사실들 위에 서 있다. 추측이 아니다.

**`-f` 필드는 명시적 `--method GET`에서 URL 쿼리 파라미터가 된다.**

```
지금:  GET /api/v4/projects/…/merge_requests?source_branch=feat/
-f:    GET /api/v4/projects/…/merge_requests?per_page=100&source_branch=feat%2F%23123&state=opened
```

잔여 항목 문서는 "`fields`로 대체할 수 없다 — 쿼리 직렬화는 `--input` 모드에서만"
이라고 적었는데 **틀렸다.** `--method` 없이 필드를 붙이면 glab이 요청을 POST로
바꾸기 때문에 그렇게 보였을 것이다. `api()`는 이미 항상 `--method`를 넘긴다.

**지금 버그는 기록보다 나쁘다.** `#` 뒤가 프래그먼트로 잘리면서 `source_branch`만
깨지는 것이 아니라 `state=opened`와 `per_page=100`도 함께 사라진다. 닫힌·머지된
MR까지 후보에 들어온다.

**`-i`의 출력 바이트 모양.** 상태줄은 `\n`으로, 헤더는 `\r\n`으로 끝나고 본문
구분자는 `\r\n\r\n`이다.

```
b'HTTP/2.0 200 OK\nCache-Control: …\r\nCf-Ray: …\r\n\r\n{"id":…}'
```

**`-i`는 `--paginate`와 같이 쓰면 페이지마다 헤더 블록을 낸다.** `per_page=5`로
3페이지를 강제했더니 상태줄이 1·39·78행에 끼어 ndjson 사이에 박혔다.

**실패 시.** exit 1, stdout에 에러 본문(`{"message":"404 Not found"}`), stderr에
`glab: 404 Not found (HTTP 404)`. 403도 같은 형식이다.

**성공했지만 비어 있는 응답**은 `[]` + exit 0이다 (`draft_notes`).

**`-F key=@-`는 stdin을 문자열로 읽는다.** glab 공식 문서가 리치/마크다운 본문에
이 형태를 권장한다. 답글이 `{`나 `true`로 시작해도 JSON으로 재해석되지 않는다 —
지금 전송 방식은 맞고 바꾸지 않는다.

## 3. R3 — `glab.api()`

### 3.1 시그니처

```python
def api(
    path: str,
    *,
    method: str = "GET",
    query: dict[str, str] | None = None,
    fields: dict[str, str] | None = None,
    body: tuple[str, str] | None = None,
    paginate: bool = False,
) -> Any
```

`check` 매개변수는 **사라진다** (§3.3).

### 3.2 `query` — `-f`, `fields` — `-F`

둘을 나누는 것은 취향이 아니라 타입 때문이다.

| | 플래그 | 가는 곳 | 이유 |
|---|---|---|---|
| `query` | `-f` (`--raw-field`) | URL 쿼리 | 값이 전부 문자열이다. `-F`는 `100`을 정수로, `[`로 시작하는 값을 배열로 바꾼다 |
| `fields` | `-F` (`--field`) | JSON 본문 | `resolved=true`가 JSON 불리언이어야 한다 |

`query`는 `method`가 `GET`이나 `DELETE`가 아니면 `ValueError`를 던진다(MUST).
다른 메서드에서 `-f`는 본문으로 가므로 조용히 틀린 요청이 된다.

호출처는 한 곳이다.

```python
glab.api(
    f"{PROJECT}/merge_requests",
    query={"source_branch": branch, "state": "opened", "per_page": "100"},
)
```

### 3.3 상태 코드와 예외

`paginate=False`일 때 `-i`를 붙인다. `paginate=True`면 붙이지 않는다 — 페이지마다
헤더가 끼어 ndjson 파싱이 깨지기 때문이고, 하필 그 경로(`pull`의 discussions)가
**상태 코드를 쓰지 않는 유일한 경로**다. 실패하면 그냥 네트워크 실패이고
`push_error`를 쓰지 않는다.

**대가를 알고 받는다.** 그 경로에서 404가 나도 `status`는 `None`, `reason`은
`network`가 된다. 받아들이는 이유는 `reason`의 유일한 소비자가
`local.push_error`이고 `push`는 paginate를 쓰지 않기 때문이다 — 틀린 `reason`이
기록으로 남을 경로가 없다. 사용자에게 보이는 메시지에는 glab의 stderr가 그대로
들어가므로 원인은 드러난다.

응답 분해: 첫 줄에서 `HTTP/<버전> <코드> <사유>`의 코드를 읽고, 첫 `\r\n\r\n`
(없으면 `\n\n`) 뒤를 본문으로 삼는다.

실패(`returncode != 0`)는 **예외**다.

```python
class GlabError(NetworkError):        # exit_code 5 를 그대로 물려받는다
    status: int | None
    reason: str                       # data-model.md §4.8 의 열거값
    retryable: bool
```

| 상태 | `reason` | `retryable` |
|---|---|---|
| 403 | `forbidden` | false |
| 404 | `not-found` | false |
| 409 | `conflict` | false |
| 5xx | `unknown` | **true** |
| 상태를 알 수 없음 | `network` | true |
| 그 외 | `unknown` | false |

`retryable`은 **시간이 지나면 같은 요청이 성공할 수 있는가**로 정한다. 그래서
`network`와 5xx만 참이다. 409는 같은 요청을 다시 보내도 같은 결과이고 호출자가
재pull해야 한다 — 재시도 가능으로 표시하면 에이전트가 루프를 돈다 (`cli.md` §9의
`retryable: false`가 막으려는 것과 같은 실패 양상). 403·404도 마찬가지다.

`GlabError`가 `NetworkError`를 상속하므로 **종료 코드 계약(exit 5)과 기존 호출처
7곳은 바뀌지 않는다.** `push`만 `except GlabError`로 받아 `push_error`를 쓴다.

### 3.4 `check=False`의 제거

유일한 사용처인 `mr.draft_notes_available`이 바뀐다.

```python
def draft_notes_available(iid: int) -> bool:
    try:
        glab.api(f"{PROJECT}/merge_requests/{iid}/draft_notes")
    except GlabError:
        return False
    return True
```

동작은 지금과 같다(장애든 미지원이든 `draft_notes: false`). 달라지는 것은 예외가
`status`를 들고 오므로 "404 — 이 GitLab이 draft notes를 지원하지 않음"과
"네트워크 장애"를 구분할 **수단이 생긴다**는 것이다. 구분해서 무엇을 할지는
`--draft`를 만드는 12단계의 몫이고, 이 과제에서는 쓰지 않는다.

## 4. R4 — 가짜 `glab` 하네스

### 4.1 `routes.json` 계약

라우트 값이 **응답 목록**이다. 호출 순서대로 소비하고, 목록이 소진되면 마지막
것이 반복된다.

```jsonc
{
  "GET projects/:fullpath/merge_requests/1234/discussions": [
    { "status": 200, "pages": ["p0.ndjson", "p1.ndjson"] }
  ],
  "POST projects/:fullpath/merge_requests/1234/discussions/abc/notes": [
    { "status": 201, "file": "r3.json" },
    { "status": 403, "body": "{\"message\":\"403 Forbidden\"}" }
  ]
}
```

응답 하나는 `{status, file | body | pages}`다. `status`의 기본값은 200,
본문의 기본값은 빈 문자열이다.

`Harness.route()`는 지금의 호출 모양을 그대로 받는다 — 단일 응답은 길이 1의
목록으로 정규화된다. 기존 테스트는 수정 없이 통과해야 한다(MUST). 새 기능은
`route_seq()`(호출별 응답)와 `route(pages=[...])`로 쓴다.

### 4.2 하네스가 실물처럼 굴어야 하는 것

이 넷이 실물과 어긋나면 R6·R7과 같은 종류의 거짓 통과가 다시 생긴다. 가짜 glab은
"우리 파서가 읽기 쉬운 것"이 아니라 **"진짜 glab이 내는 것"**을 내야 한다(MUST).

1. **`-i`가 argv에 있을 때만** 헤더를 낸다. 바이트 모양은 §2 실측 그대로 —
   상태줄은 `\n`, 헤더는 `\r\n`, 구분자는 `\r\n\r\n`.
2. `-i`와 `--paginate`가 함께면 **페이지마다** 헤더 블록을 낸다.
   `api()`는 그 조합을 보내지 않는다(§3.3). 그럼에도 구현하는 이유는 이것이
   **가드**이기 때문이다 — 나중에 누군가 paginate 경로에 `-i`를 붙이면 하네스가
   실물과 똑같이 깨뜨려 테스트가 잡는다. 하네스가 그 조합을 조용히 잘 처리하면
   실제 GitLab에서만 깨진다.
3. `status >= 400`이면 exit 1, stdout에 에러 본문, stderr에
   `glab: <메시지> (HTTP <코드>)`.
4. `--paginate`면 `pages`의 파일들을 순서대로 이어 붙인다.

등록되지 않은 경로에서 요란하게 실패하는 지금 동작은 **그대로 둔다** —
조용히 통과시키면 테스트가 거짓으로 녹색이 된다 (`testing.md` §2).
`MRQ_GLAB_FAIL_AT`(프로세스 단위 사망)도 그대로다. 그것은 HTTP 실패가 아니라
크래시를 흉내 내는 별개의 장치이고, `testing.md` §6의 "N번째 호출에서 사망"이
그것을 쓴다.

### 4.3 추가되는 픽스처

- **2페이지 discussions.** 지금 `discussions.ndjson`을 두 파일로 나눈다.
  `testing.md` §3이 요구하는데 표현할 방법이 없어 빠져 있던 항목이다.
- **403·404 에러 본문.** `{"message":"403 Forbidden"}` 등. 실측에서 받은 그대로.

`access_level: 20` 프로젝트는 응답 **본문**이므로 이미 표현 가능하고
`test_mr.py`가 덮고 있다. 추가하지 않는다.

## 5. 테스트

`glab`과 `git`을 모킹하지 않는다는 규율은 그대로다 (`testing.md` §2).

| 대상 | 단언 |
|---|---|
| `query` 인코딩 | argv에 `--method GET`과 `-f source_branch=feat/#123`이 있다 |
| `query` + 비GET | `ValueError` |
| `mr.detect` | `#`·`&`·`%`·`+`를 담은 브랜치에서 올바른 MR을 찾는다 |
| `-i` 부착 | `paginate=False`면 argv에 `-i`, `True`면 없다 |
| 상태 파싱 | 200/201/403/404에서 `GlabError.status`가 맞다 |
| `reason`·`retryable` | §3.3의 표 전체 |
| paginate 2페이지 | 두 파일의 ndjson이 순서대로 이어진 리스트가 된다 |
| 호출별 응답 | 같은 경로의 1·2번째 호출이 다른 결과를 낸다 |
| `draft_notes_available` | 404와 네트워크 장애 모두 `False` |
| 종료 코드 | `GlabError`가 exit 5로 나간다 |

**하네스 자체의 충실도**는 `glab_mod.api()`를 통해 검증한다 — 하네스가 내는
바이트를 우리 파서가 읽어 기대한 값이 나오는지. 하네스의 내부를 직접 단언하지
않는다. 그러면 "하네스가 자기 자신과 일치한다"는 동어반복이 된다.

## 6. 범위 밖

- **`--input` / `Content-Type` / bracket 키.** 계획 3의 페이로드(`body`,
  `resolved`, `note`, `in_reply_to_discussion_id`, `resolve_discussion`)는 전부
  평평하다. 415와 bracket 키 함정은 **위치 코멘트를 새로 만들 때** 걸리고,
  `mrq`는 기존 스레드에 답글만 단다. 중첩 객체조차 `-F 'position={…}'`로 보낼 수
  있어 `--input`이 필요 없다. 실측으로 얻은 내용이므로 버리지 않고 잔여 항목
  문서의 future work(위치 코멘트 생성) 쪽으로 옮긴다.
- **R5**(사라진 스레드의 `local.*` 소실), **R8**(`todo` 답글 경고). 잔여 항목
  문서에 남는다.
- **`push` 자체.** 9단계이고 계획 3이다.
- `discussions._to_thread`의 사전식 `max()` 등 "코드 모양" 항목들.

## 7. 문서 갱신

구현이 끝나면 이 설계 문서는 삭제하고 내용을 아래로 옮긴다
(CLAUDE.md의 작업 방식).

- `spec/cli.md` §3 — "알려진 공백: `api()`는 HTTP 상태를 돌려주지 않는다" 절을
  실제 계약으로 교체. `query`/`fields` 구분과 `-i`·paginate 예외를 규범으로
- `spec/testing.md` §2 — `routes.json` 계약과 하네스가 실물처럼 굴어야 하는 넷
- `spec/testing.md` §3 — 2페이지 픽스처가 더 이상 빠져 있지 않다
- `docs/decisions/0010-*` — 상태를 튜플이 아니라 **예외**로 나르기로 한 선택.
  잔여 항목 문서가 `(status, data)`를 제안했으므로 갈림길 기록이 필요하다
- `docs/plans/README.md` — 전 과제 표의 R3·R4를 완료로
- 잔여 항목 문서 — R3·R4 삭제, `--input` 관련 내용을 future work로 이동

## 8. 위험

- **`-i`를 모든 비paginate 호출에 붙인다.** 응답마다 헤더를 파싱하는 비용이
  생기지만 호출 수가 MR당 한 자리수라 무시할 수 있다. 호출자가 고르게 하면
  "어떤 호출은 status가 있고 어떤 호출은 없다"가 되어 더 나쁘다.
- **하네스 변경이 모든 `glab` 테스트를 지나간다.** 기존 `route()` 호출 모양을
  보존하는 것이 이 위험을 막는 장치다. 기존 테스트가 하나라도 수정되어야 한다면
  정규화가 잘못된 것이다.
- **`-f`의 쿼리 직렬화는 glab 1.114에서 확인한 동작이다.** 문서화되어 있고
  (`--input` 모드 외에도 GET/DELETE에서 쿼리가 된다고 공식 문서가 명시한다)
  `doctor`가 기능 확인을 담당하는 구조(`cli.md` §3)이므로, 10단계에서
  `doctor`의 확인 항목에 이것을 더하는 것이 자연스럽다. 이 과제에서는 하지 않는다.
