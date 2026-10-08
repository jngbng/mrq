# 스펙: 재앵커링

규범 문서. 관련: FR-003

코멘트의 `position`은 MR의 `head_sha` 기준인데 로컬 작업 트리는 이미 수정된 상태다.
그대로 쓰면 엉뚱한 줄에 진단이 붙어 즉시 신뢰를 잃는다. 이 문서의 정확도가 제품의
성공 기준(코멘트 15개 / 30분)을 좌우한다.

**목표: `exact ≥ 75%`, `stale ≤ 10%`.** 회귀 테스트로 강제한다.

---

## 1. 입력과 출력

| | |
|---|---|
| 입력 | `position`(서버 좌표), `anchor`(head_sha 내용), 현재 작업 트리 |
| 출력 | `location` = `{path, line, line_end, confidence, method}` |

실행 시점:

| 명령 | 재앵커링 | 네트워크 |
|---|---|---|
| `pull` | ✓ | ✓ |
| `sync` | ✓ | — |
| `reanchor` | ✓ | — |
| `push` | — (내부 `sync`가 수행) | ✓ |

`sync`가 재앵커링을 포함하는 것이 중요하다. 에디터 저장 훅이 `sync` 하나만 호출하면
md 반영과 위치 갱신이 함께 끝나고, 둘이 따로 돌아 중간 상태가 보이는 일이 없다. 둘 다
로컬 작업이므로 "네트워크는 CLI만" 원칙과 충돌하지 않는다.

---

## 2. 선행 조건: `head_sha` 확보

`anchor` 추출과 git 매핑은 `head_sha`가 로컬 object DB에 있어야 가능하다.

```sh
git cat-file -e <head_sha>^{commit}                 # 있는지 확인
git fetch origin refs/merge-requests/<iid>/head     # 없으면 가져온다
git fetch origin <source_branch>                    # 위가 막혀 있으면 대안
```

세 번째까지 실패하면 git 매핑 전체를 건너뛰고 문자열 탐색 경로로 degrade한다(MUST).
이때 `pull`은 경고를 한 번 출력해야 한다(MUST) — 조용히 품질이 떨어지면 안 된다.

```
⚠ head_sha abc1234를 가져올 수 없습니다. 위치 정확도가 떨어집니다 (anchor-search only)
```

---

## 3. `anchor` 추출 (`pull`만)

`anchor`는 `head_sha` 시점의 파일 내용에서 뽑는다. `git show <head_sha>:<new_path>`로
읽는다 — 작업 트리에서 읽으면 안 된다(MUST NOT). 이미 바뀌어 있다.

| 필드 | 내용 |
|---|---|
| `line` | `position.new_line` 위치의 줄. 개행 제외, 그 외는 바이트 그대로 |
| `context_before` | 바로 앞 **3줄**. 파일 시작에 걸리면 있는 만큼 |
| `context_after` | 바로 뒤 **3줄**. 파일 끝에 걸리면 있는 만큼 |

3줄로 정한 이유는 §5.2 a단계의 중복 후보 점수 계산에 필요한 최소량이다. 더 늘리면
json만 커지고 점수 품질은 거의 개선되지 않는다.

`old_line`만 있는 코멘트는 `git show <start_sha>:<old_path>`에서 같은 방식으로 뽑는다.

### `anchor.hunk` — 리뷰어가 본 diff

```sh
git diff -U3 <start_sha> <head_sha> -- <new_path>
```

이 diff가 MR이 보여주는 변경 전체이므로, 여기서 대상 줄을 포함하는 hunk 하나를
그대로 떼어 저장한다(MUST). hunk 헤더(`@@ ... @@`)를 포함한다.

- `start_sha`가 로컬에 없으면 `head_sha`와 같은 방식으로 fetch한다 (§2)
- 그래도 없거나 해당 줄을 포함하는 hunk를 찾지 못하면 `hunk: null`이다.
  렌더러가 `context_before` + `line` + `context_after`로 폴백한다
  (`review-md.md` §4)

discussions 응답에는 hunk가 없다. GitLab의 diffs 엔드포인트를 쓰지 않고 로컬 git으로
구하는 이유는 호출이 늘지 않고, `head_sha`/`start_sha` 확보 경로를 이미 갖고 있기
때문이다.

---

## 4. `pull` 1회당 한 번: 경로 맵

```sh
git diff -M --name-status <head_sha>
```

pathspec 없이 한 번 실행해 `R100 old/path new/path` 항목으로 rename 맵을 만든다(MUST).
pathspec을 주면 rename 탐지가 동작하지 않으므로 전체로 한 번 돌린다. 호출은 스레드
수와 무관하게 1회다.

- `R` 항목 → `position.new_path`를 새 경로로 바꿔 매핑을 계속한다
- `D` 항목 → `stale` 확정, 이후 단계를 건너뛴다

---

## 5. 스레드별 알고리즘

`position`이 `null`이거나 `position_type != "text"`이면 `location`을 `null`로 두고
끝낸다(MUST). 재앵커링 통계에서도 제외한다 — 위치를 찾지 못한 것이 아니라 위치가
없는 것이다.

### 5.1 1단계 — git 라인 매핑 (주 전략)

```sh
git diff -M -U0 <head_sha> -- <mapped_path>
```

`@@ -a,b +c,d @@` 헤더만 파싱해 `head_sha` → 작업 트리 라인 맵을 만든다.

- hunk 밖의 줄은 누적 delta만큼 이동한다
- 삭제 영역 안의 줄은 매핑이 없다
- 작업 트리와 비교하므로 **커밋하지 않은 수정까지 반영된다**

매핑 결과에 대해 **반드시 내용 검증을 해야 한다**(MUST) — 매핑된 줄이 `anchor.line`과
같은지. 통과하면 `{confidence: "exact", method: "git-diff"}`로 확정하고 종료한다.

대부분의 스레드가 여기서 끝나야 정상이다.

### 5.2 2단계 — 문자열 탐색 (fallback)

1단계가 매핑을 주지 못했거나 내용 검증에 실패한 경우:

```
a. 탐색 창(매핑 추정 위치, 없으면 position.new_line의 ±50)에서
   anchor.line 완전 일치
     후보 1개  → exact / anchor-search
     후보 여러 개 → context_before/after 겹침 점수로 선택 → fuzzy / anchor-search
b. 같은 창에서 strip() 비교 (공백·인덴트만 바뀐 경우)
     후보 1개 → fuzzy / anchor-search
c. 파일 전체에서 anchor.line이 유일하면 채택 → fuzzy / anchor-search
d. 실패 → stale / none
```

**2c(파일 전체 유일성 탐색)가 반드시 있어야 한다**(MUST). 함수 블록이 파일 안에서 멀리
옮겨지면 git은 delete + add로 보고하고 ±50 창도 벗어난다 — 리팩터링 중인 MR에서
흔하다. "파일 전체에서 유일하면"이라는 유일성 가드가 오탐 없이 이 경우를 건진다.

유일성 가드 없이 전체 탐색을 하면 안 된다(MUST NOT). `}` 같은 줄에 붙어 즉시 신뢰를
잃는다.

### 5.3 3단계 — 삭제된 줄 (old-side 코멘트)

`position.new_line`이 없고 `old_line`만 있는 코멘트는 `head_sha`에 존재하지 않는 줄을
가리킨다. 매핑할 대상 자체가 없다.

`anchor.context_before`의 마지막 줄(보통 살아남은 context 줄)을 1·2단계로 위치시키고
**그 바로 아래**에 붙인다 → `{confidence: "fuzzy", method: "context-anchor"}`.
실패하면 `stale`이다.

삭제된 코드에 대한 코멘트는 "이 근처에서 지운 것에 대한 말"이므로 근처에 붙이는 것이
맞고, 파일 1행에 몰아두는 것보다 유용하다.

### 5.4 멀티라인 (`position.line_range`)

`start`와 `end`를 각각 1~3단계로 매핑한다.

- 둘 다 성공 → `location.line` / `location.line_end`
- 하나라도 실패 → `start`만 사용, `line_end: null`, `confidence`를 `fuzzy`로 강등

---

## 6. 에디터가 해도 되는 보정의 범위

재앵커링 로직을 Python·elisp·TypeScript에 세 번 구현하면 셋이 미묘하게 달라진다.
동시에, 저장하지 않은 버퍼에서 진단이 틀린 줄에 떠 있으면 사용자가 위치를 신뢰하지
않는다. 그래서 역할을 나눈다.

**에디터가 할 수 있는 것 — 이것만이다(MUST):**

- 저장하지 않은 버퍼 안에서 `location.line ± 200` 범위를 탐색
- `anchor.line` 완전 일치 → 실패하면 `strip()` 일치
- **후보가 유일할 때만** 채택. 아니면 `location.line`을 그대로 쓴다

**에디터가 하면 안 되는 것(MUST NOT):**

- `git` 호출
- 네트워크 호출
- `confidence` / `method` 변경
- 탐색 창 확대
- `context_before` / `context_after` 점수 계산
- `review.json` 직접 쓰기

이 범위면 elisp 10줄, TypeScript 15줄 수준이고 세 구현이 어긋날 여지가 거의 없다.
무거운 부분(git diff 기반 매핑, rename 추적, context 점수)은 전부 CLI 전담이다.

---

## 7. 품질 가시화

`pull`과 `sync`는 재앵커링 결과를 한 줄로 출력해야 한다(MUST).

```
reanchored: exact 12 · fuzzy 2 · stale 1   (head abc1234)
```

성공 기준은 처리 시간이지만 시간은 사후에만 측정된다. `fuzzy + stale` 비율이 선행
지표다 — 이 값이 커지면 사용자가 코멘트마다 위치를 눈으로 확인하게 되고 시간 예산이
무너진다. 수치가 보이면 알고리즘을 튜닝할 근거가 생긴다.

`mrq status`도 같은 수치를 `anchors` 행에 포함한다.

---

## 8. 테스트 시나리오

**git을 모킹하지 않는다**(MUST NOT). 검증 대상이 `git diff -U0`의 실제 출력과 hunk
파서의 일치이므로, 임시 디렉터리에 실제 저장소를 만들고 커밋과 작업 트리 변경을 만든다.

| # | 시나리오 | 기대 |
|---|---|---|
| 1 | 앵커 줄 위에 줄 삽입 | `exact` / `git-diff`, line 증가 |
| 2 | 앵커 줄 아래에 줄 삽입 | `exact` / `git-diff`, line 불변 |
| 3 | 앵커 줄 내용 수정 | `stale` 또는 context로 `fuzzy` |
| 4 | 인덴트만 변경 | `fuzzy` / `anchor-search` (strip 매치) |
| 5 | 앵커 줄 삭제 | `stale` |
| 6 | 블록을 파일 내 먼 곳으로 이동 | `fuzzy` / `anchor-search` (2c 경로) |
| 7 | 파일 rename | `exact`, `location.path`가 새 경로 |
| 8 | 파일 삭제 | `stale` |
| 9 | 동일 내용 줄이 창 안에 여럿 | context 점수로 올바른 줄, `fuzzy` |
| 10 | 멀티라인 `line_range` | `line` + `line_end` |
| 11 | old-side(삭제된 줄) 코멘트 | `fuzzy` / `context-anchor` |
| 12 | `head_sha` fetch 실패 | 경고 출력, `anchor-search`로 degrade |

### 품질 회귀 게이트

위 시나리오가 섞인 코퍼스(스레드 20개 이상) 하나에 대해 다음을 단언한다(MUST).

```
exact >= 75%
stale <= 10%
```

선행 지표에 테스트를 걸어 알고리즘 튜닝이 조용히 퇴보하지 않게 한다.
