<!-- mrq:file schema=1 iid=1234 head=abc1234 rendered=2026-10-11T09:12:01+09:00 -->
<!-- mrq:help
  체크박스: [ ] 미처리 · [x] 완료(resolve) · [~] 답글만 · [-] 건너뜀
  답글은 각 스레드의 `### reply` 아래에 씁니다. 표·코드블록·--- 모두 자유롭게 쓸 수 있습니다.
  `<!-- mrq:... -->` 줄은 지우거나 수정하지 마세요. 그 외의 모든 내용은 무시됩니다.
  다 쓴 뒤 `mrq sync`, 확인은 `mrq status`, 전송은 `mrq push`.
-->

# !1234 Add retry logic to API client

head abc1234 · pulled 09:12 · unresolved 4 · exact 3 fuzzy 1 stale 1

<!-- mrq:7a0b1c2d3e4f v:735c74 -->
## [ ] (general) — @kim  `no-reply`

> **@kim** 2026-10-05 13:40
> 전반적으로 좋은데 타임아웃 쪽만 한 번 봐주세요.

### reply


<!-- mrq:d4e5f6a1b2c3 v:c917ae -->
## [x] src/api/client.py:7 — @jdoe

```diff
@@ -84,6 +84,9 @@ def fetch(url):
     session = make_session()
+    resp = session.get(url)
```

> **@jdoe** 2026-10-05 14:02
> 타임아웃 설정이 빠졌습니다. 기본값이면 무한 대기할 수 있어요.

### reply

전송 전 답글이 있으므로 --all 없이도 나와야 한다.

<!-- mrq:a1b2c3d4e5f6 v:735c74 -->
## [ ] src/api/client.py:102 — @jdoe

```diff
@@ -84,6 +84,9 @@ def fetch(url):
     session = make_session()
+    resp = session.get(url)
```

> **@jdoe** 2026-10-05 14:02
> 타임아웃 설정이 빠졌습니다. 기본값이면 무한 대기할 수 있어요.

### reply


<!-- mrq:c3d4e5f6a1b2 v:92d942 -->
## [~] src/api/legacy.py:1 — @park  `stale`

```diff
@@ -84,6 +84,9 @@ def fetch(url):
     session = make_session()
+    resp = session.get(url)
```

> **@park** 2026-10-05 14:02
> 타임아웃 설정이 빠졌습니다. 기본값이면 무한 대기할 수 있어요.

### reply

이건 의도된 동작입니다.

| 설정 | 이전 | 이후 |
|---|---|---|
| timeout | 없음 | 10s |

---

그래서 그대로 둡니다.

<!-- mrq:b2c3d4e5f6a1 v:735c74 -->
## [ ] src/api/session.py:42 — @park  `fuzzy`

```python
def build(cfg):
    timeout = None
    return Session(timeout)
```

> **@park** 2026-10-05 16:10
> 코드 블록을 포함한 지적입니다.
>
> ```python
> Session(timeout=10)
> ```
>
> 확인 부탁합니다.

### reply
