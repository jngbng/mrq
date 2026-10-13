# 스펙: 테스트 전략

공통 인프라와 횡단 테스트. 기능별 테스트는 각 스펙 문서의 테스트 절에 있다.

| 영역 | 테스트 위치 |
|---|---|
| 리포 구조·툴체인·적합성 테이블 | `repo-layout.md` |
| 재앵커링 시나리오 12종 + 품질 게이트 | `reanchoring.md` §8 |
| md 라운드트립 property, 에러/경고 표 | `review-md.md` §8 |
| 충돌 감지 판정 표 | 아래 §4 |
| push 멱등성·크래시 복구 | 아래 §5 |
| Emacs ERT | `editor.md` §3.5 |

---

## 1. 어디에 투자하는가

위험이 몰린 곳은 **재앵커링**과 **md 파서** 두 곳이다. 네트워크 레이어는 `glab`에
위임했으므로 얇고, 검증할 것은 "우리가 만든 argv가 맞는가"뿐이다.

---

## 2. 가짜 `glab`을 PATH에 꽂는다

`subprocess.run`을 모킹하지 않는다(MUST NOT). `cli/tests/bin/glab`에 실행 가능한
스크립트를 두고 테스트가 PATH 앞에 붙인다.

```
cli/tests/bin/glab
  MRQ_GLAB_FIXTURES   응답 디렉터리
  MRQ_GLAB_LOG        호출 기록 (argv + stdin)
  MRQ_GLAB_FAIL_AT    N번째 호출에서 실패 (크래시 복구 테스트)
  매칭 실패 → exit 1 + 에러 메시지
```

매칭 실패를 조용히 통과시키면 안 된다(MUST NOT). 테스트가 거짓 통과한다.

### 타임존을 고정한다

렌더러는 시각을 로컬 타임존으로 변환한다(`review-md.md` §5). 따라서 골든의
결정성은 테스트가 TZ를 고정해 얻어야 한다(MUST) — `conftest`가 `TZ`를 세팅하고
`time.tzset()`을 부른다.

**UTC로 고정하면 안 된다**(MUST NOT). 픽스처의 시각도 UTC이므로 변환이 일어나는
경우와 일어나지 않는 경우의 출력이 같아져, 테스트가 변환을 전혀 검증하지 못한다.

같은 이유로 **픽스처의 시각은 GitLab이 실제로 주는 형식**이어야 한다(MUST) —
UTC, 밀리초, `Z` 접미사(`"2026-10-12T23:07:20.443Z"`). 손으로 쓴 `+09:00`
픽스처가 로컬 타임존과 같으면 변환 버그가 골든을 통과한다. 실제로 그렇게
통과하고 있었다.

모킹보다 이쪽이 나은 이유는 **버그가 argv 조립에서 나기 때문**이다.

- `-F body=@-`로 stdin을 넘기는지
- `--paginate --output ndjson`을 쓰는지
- `projects/:fullpath/...` 경로가 맞는지
- POST 본문에 표가 섞인 긴 답글이 깨지지 않고 들어가는지

`subprocess.run`을 모킹하면 이것을 전부 못 본다. 가짜 glab은 stdin까지 기록하므로
"실제로 보낸 답글 본문"을 그대로 단언할 수 있다.

---

## 3. 픽스처

픽스처는 소유자에 따라 두 곳으로 나뉜다 (`repo-layout.md` §2).

| 위치 | 내용 | 읽는 주체 |
|---|---|---|
| `cli/tests/fixtures/` | GitLab API 응답 | CLI만 |
| `testdata/review/` | 완성된 `review.json` 샘플 | 세 구현 전부 |
| `testdata/conformance/` | 앵커 검색 적합성 테이블 | 세 구현 전부 |

### `cli/tests/fixtures/` — GitLab API 응답

실제 API 응답을 저장한다. 반드시 포함할 것:

- `individual_note: true` 스레드
- `DiffNote` + `position` + `line_range`가 있는 멀티라인
- `system: true` 노트가 섞인 응답 (`pull`에서 걸러지는지)
- `suggestions[]`가 달린 노트
- 서버에서 이미 resolve된 스레드
- `resolvable: false` 스레드
- `position`이 없는 general 코멘트
- 2페이지 이상 응답 (ndjson 스트리밍)
- `permissions.project_access.access_level`이 20인 프로젝트 (403 경로)
- `position_type`이 `image`인 노트

### 실제 API 응답과 대조한다

손으로 쓴 픽스처는 실제 응답과 어긋날 수 있다. 실험용 프로젝트
**https://gitlab.com/jngbng/mr-helper** 에 커밋과 MR을 만들어 실제 응답을 받고,
`cli/tests/fixtures/` 의 픽스처와 필드 구성을 대조한다.

```sh
glab api "projects/jngbng%2Fmr-helper/merge_requests/<iid>/discussions" \
  --paginate --output ndjson
```

이것은 **일회성 대조**이며 테스트 경로가 아니다. 단위 테스트는 네트워크를 쓰지
않는다(§2). 픽스처를 갱신할 때는 사용자 이름·토큰·사내 호스트명이 섞여 들어가지
않는지 확인한다.

### `testdata/` — 공유 데이터

- `review/*.json` — 완성된 `review.json` 샘플. 세 구현이 모두
  `schema/review.schema.json`으로 검증한다
- `conformance/anchor.json` — 에디터 보정 로직의 적합성 테이블. 세 구현이 모두 같은
  테이블을 돌린다. 형식은 `repo-layout.md` §4.1

중복된 유일한 로직(앵커 한 줄 검색)이 세 언어에서 같게 동작하는지는 **이 테이블만이
강제한다.** `make conformance`로 교차 실행한다.

---

## 4. 충돌 감지

`data-model.md` §5.2의 판정 표를 그대로 케이스화한다.

| md의 값이 `v`와 | 렌더 후 json 변경 | 기대 |
|---|---|---|
| 같다 | 아니오 | json 유지, exit 0 |
| 같다 | 예 (cli) | json 유지, exit 0 — **거짓 충돌이 없어야 한다** |
| 다르다 | 아니오 | md 적용, exit 0 |
| 다르다 | 예 (cli) | 충돌, **아무것도 쓰지 않고** exit 3 |
| `v` 토큰 없음 | 아니오 | md 적용 |
| `v` 토큰 없음 | 예 | 충돌, exit 3 |

두 번째 행이 `v` 해시를 도입한 이유이고, 네 번째 행이 "하나라도 충돌하면 전체 거부"를
지키는지 본다. `sync --prefer md|json`도 같은 표로 검증한다.

---

## 5. 조용히 틀리는 경로

단위 테스트가 없으면 사람이 데이터를 잃고도 모르는 경로들이다.

| 시나리오 | 기대 |
|---|---|
| 시스템 노트만 추가된 스레드에 `push` | 건너뛰지 않는다. `updated_at`/`note_count`를 필터 후 값으로 계산하는지 |
| 미전송 답글이 있는데 서버에서 resolve됨 → `pull` | `--all` 없이도 `review.md`에 렌더된다 |
| 다른 MR의 `review.md`를 `sync` | exit 1, 아무것도 쓰지 않음 |
| `mr_state == merged`에 `push` | 확인 요구. `--force`로 진행 |
| `current`가 가리키는 MR을 `clean` | `current`도 제거되어 끊어진 심링크가 없다 |
| `pull` 후 브랜치 변경 → `status`/`list` | 두 브랜치 이름과 `mrq pull` 안내를 stderr로 경고. 종료 코드는 그대로 (읽기 경로를 끊지 않는다) |
| `pull` 후 브랜치 변경 → `sync`/`reply`/`state` | exit 1, **아무것도 쓰지 않음**. 엉뚱한 MR에 답글을 남기지 않는다 (`cli.md` §2) |
| `pull` 후 브랜치 변경 → `reanchor` | exit 1, **아무것도 쓰지 않음**. 다른 브랜치의 작업 트리로 계산한 `location`/`confidence`가 그럴듯한 틀린 값으로 남지 않는다 |
| `reply -m ""` 또는 빈 stdin | exit 1. 미전송 답글이 빈 본문으로 덮이지 않는다 |
| 답글이 코드 펜스를 닫지 않아 다음 스레드 블록이 삼켜짐 | exit 2, 아무것도 쓰지 않음. 삼킨 앵커 id를 보고한다 (`review-md.md` §7) |

---

## 6. push 멱등성과 크래시 복구

`MRQ_GLAB_FAIL_AT`으로 N번째 호출에서 죽게 만든다.

| 시나리오 | 기대 |
|---|---|
| 답글 POST 성공 직후 사망 | 재실행 시 `pushed_hash` 때문에 재전송 없음 |
| `pushed_hash` 기록 직전 사망 | 재실행 시 서버 스냅샷의 동일 본문 체크가 막는다 |
| resolve 403 | `push_error` 기록, state `replied` 강등, **재실행 시 resolve 재시도 없음** |
| 서버에서 변경된 스레드 | 건너뜀. `--force`로 전송 |
| 스레드 3개 중 2번째에서 사망 | 1번째 결과가 json에 남아 있음 |

마지막 행을 확인하려면 중간 상태의 json을 직접 읽어 단언한다. 매 스레드 후 flush를
하는지가 검증 대상이다.

---

## 7. 계약 테스트

| 대상 | 방법 |
|---|---|
| 종료 코드 | `cli.md` §2의 표 전체. 특히 2 / 3 / 4의 구분 |
| `--json` 출력 | `jsonschema`로 검증. **stdout에 JSON 외의 것이 없는지** 별도 단언 |
| `review.json` | `schema/review.schema.json`으로 검증. 모든 쓰기 경로 뒤에 적용 |
| 스키마 버전 | 상위 버전 파일 → exit 7, 아무것도 쓰지 않음 |
| 원자성 | 쓰기 중간에 프로세스를 죽여도 기존 json이 온전한지 |
| 락 | 두 프로세스가 동시에 `sync`할 때 직렬화되는지 |
| 적합성 | 세 구현이 `testdata/conformance/anchor.json`을 통과하는지 |
| 상태 부재 | `.mrq/`가 없을 때 `pull`/`doctor` 외 전부 exit 1 |
| `mrq:file` 검증 | 다른 iid의 `review.md`를 `sync`하면 exit 1. 주석이 아예 없으면 exit 2 (검증할 근거가 없다) |

`review.json` 스키마 검증을 모든 쓰기 경로 뒤에 거는 것이 중요하다 — 스펙과 구현이
갈라지는 것을 막는 가장 싼 장치다.

---

## 8. 성공 기준 확인

"코멘트 15개 / 30분"은 단위 테스트로 잡을 수 없다. 두 단계로 나눈다.

1. **선행 지표에 테스트**: `reanchoring.md` §8의 품질 회귀 게이트 (`exact ≥ 75%`)
2. **수동 측정 1회**: 실제 MR 하나로 끝까지 돌리고 단계별 시간을 기록한다.
   https://gitlab.com/jngbng/mr-helper 에 코멘트 15개가 달린 MR을 만들어 쓴다

### 수동 측정 체크리스트

| 단계 | 측정 | 기록 |
|---|---|---|
| `mrq pull` 실행 시간 | 초 | |
| 재앵커링 결과 | exact / fuzzy / stale | |
| 위치가 틀려서 직접 찾은 코멘트 수 | 건 | |
| 코멘트별 처리 시간 | 초 (유형별) | |
| `mrq status` 확인 시간 | 초 | |
| `mrq push` 실행 시간 | 초 | |
| 총 소요 시간 | 분 | |
| 가장 시간을 많이 쓴 지점 | | |

어디서 시간이 새는지 알면 다음 라운드에 무엇을 고칠지가 정해진다. 측정 없이 추측으로
최적화하지 않는다.
