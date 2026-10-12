# 0008. 충돌 판정의 "렌더 후 json 변경" 신호를 `v` 핑거프린트로 바꾼다

날짜: 2026-10-13 · 상태: 채택 ([0002](0002-per-thread-conflict-detection.md)의
"렌더 후 json 변경" 판정 신호를 대체. 스레드 단위 판정과 여섯 행의 결과 자체는
그대로 유지한다)

## 배경

[0002](0002-per-thread-conflict-detection.md)는 스레드별 충돌 판정에 `rendered_at`,
`local.touched_at`/`touched_by`, 그리고 앵커의 `v:` 해시 세 가지를 모두 쓰기로
했다. 셋째 열("렌더 후 json 변경")은 `touched_at > rendered_at`로 구현됐다.

그런데 `docs/spec/cli.md` §10은 `reply`/`state`가 `touched_at`을 기록한 **뒤에**
md를 재렌더해 `rendered_at`을 갱신해야 한다고 못박는다(MUST). 그 순서를 그대로
따르면 CLI가 쓴 모든 변경 직후 항상 `touched_at <= rendered_at`이 성립하므로,
`touched_at > rendered_at` 비교는 정상 경로에서 **결코 참이 될 수 없다.**
`data-model.md` §5.2의 4·6행(충돌)이 죽은 코드가 되고, 사람이 그 재렌더 이전에
열어 둔 버퍼를 저장해 `sync`를 돌리면 AI가 쓴 답글이 경고도 진단도 없이
지워진다 — [0002](0002-per-thread-conflict-detection.md)가 막으려던 바로 그
실패 양상이다. task-8 코드 리뷰가 실제 저장소에서 `mrq reply`를 §10 순서대로
시뮬레이션한 뒤 그 재렌더 이전 버퍼를 저장하는 시나리오로 재현했다.

## 결정

"렌더 후 json 변경"을 타임스탬프 비교 대신 **`v` 핑거프린트 비교**로 판정한다.

```python
json_v = vhash(thread.local.state, thread.local.reply)
cli_changed = thread.local.touched_by == "cli" and (block.v is None or block.v != json_v)
```

렌더러가 앵커에 적는 `v`는 "이 md가 렌더될 때 json이 어떤 상태였는지"의
핑거프린트다. 따라서 "그 이후 json이 움직였는가"는 지금의
`local.state`/`local.reply`를 다시 해시해 `v`와 비교하는 것으로 직접 답할 수
있다 — 시계를 보지 않는다.

[0002](0002-per-thread-conflict-detection.md)가 정한 스레드 단위 판정과 여섯 행의
판정 결과(`data-model.md` §5.2)는 그대로 유지한다. 바뀌는 것은 셋째 열의
**신호**뿐이다. 게이트는 여전히 `touched_by == "cli"`다 — `push`가 남기는
`touched_by == "push"`와의 상호작용은 계획 3의 범위다.

## 근거

- `v`는 이미 §5.1이 "사람이 편집했는지"를 판정하려고 만든 핑거프린트다. 같은
  핑거프린트로 "AI가 편집했는지"도 답할 수 있으므로 새 상태를 추가하지 않는다
- 타임스탬프 비교는 초 단위 해상도에도 취약하다 — 같은 초 안에서 `touched_at`과
  `rendered_at`이 모두 기록되면 비교가 우연히도 같은 결과를 낸다. 이번 리뷰에서
  그 취약성이 먼저 발견됐고, 뒤이어 §10의 순서 자체가 비교를 영구히 무력화한다는
  것이 드러났다
- `rendered_at`은 여전히 "md를 마지막으로 렌더한 시각"으로서 `status` 표시 등에
  쓰인다. 충돌 판정에서만 빠진다

## 수용한 위험

- **`vhash` 충돌(1600만 분의 1).** §5.1이 6자를 고른 이유가 바로 이 위험을
  감당할 수준으로 낮추는 것이었다. 타임스탬프 방식이었어도 없던 위험이 아니라
  애초에 `v` 자체의 위험이며, 이번 변경으로 더 커지지 않는다
- **`v:` 토큰을 손으로 지운 뒤 CLI로 건드린 스레드는 `--prefer`로 정리할 때까지
  계속 충돌로 보고된다.** `data-model.md` §5.2 5·6행에서 `v` 토큰이 없으면
  보수적으로 "충돌"(`touched_by == "cli"`일 때) 또는 "md 적용"으로 처리한다.
  `v`가 없으면 "json이 움직였는지"를 판정할 근거가 없으므로, `touched_by ==
  "cli"`인 한 `mrq sync --prefer md|json`으로 사람이 명시적으로 정리할 때까지
  충돌 상태가 유지된다. 의도된 보수적 동작이다

## 결과

- `conflict.classify`에서 `rendered_at` 인자를 **제거한다**. `changed_after_render`와
  `_moment` 헬퍼도 삭제한다 — 죽은 코드를 남기지 않는다. 호출처는 `plan_sync`와
  테스트뿐이라 호환을 지킬 대상이 없다
- 같은 이유로 `report.py`의 `server-changed` 경고(`status`의 `updated_at > pulled_at`
  비교)도 삭제했다 — `server.*`를 `pulled_at`과 같은 스냅샷이 쓰므로 구조적으로
  거짓이고, 시계가 뒤처지면 거짓 참이 된다. `cli.md` §8 참조
- `data-model.md` §5.2의 표(여섯 행과 판정)는 그대로이고 셋째 열의 설명과 그
  앞뒤 문단만 바뀐다
- 타임스탬프 비교가 영원히 거짓이 되는 경로를 통합 테스트로 고정한다 —
  `cli.md` §10이 명시한 순서(`touched_at` 기록 → 재렌더)대로 `mrq reply`를
  시뮬레이션한 뒤, 사람이 그 재렌더 **이전** 버퍼를 저장한 경우를 재현해 exit 3
  과 양쪽 값 보존을 확인한다(`cli/tests/test_sync.py::test_sync_detects_conflict_from_a_real_reply_then_stale_buffer_save`).
  이 테스트는 옛 구현에서는 실패하고 새 구현에서만 통과하는 것을 확인했다
