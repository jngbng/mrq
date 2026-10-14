# 실측 체크리스트 — `plugin_emacs`

배치 ERT 가 못 잡는 것만 모았다: **실제 설정과의 상호작용**, 키 바인딩 충돌,
그리고 사람이 메시지를 실제로 **알아채는지**.

78개 ERT 와 적합성 테이블 16건은 이미 통과한다. 여기 있는 것은 그것들이 구조적으로
답할 수 없는 질문들이다.

대상: `gitlab.com/jngbng/mr-helper` MR `!1` (코멘트 15개).

---

## 준비

```elisp
;; ~/.emacs.d/modules_jbseo/init-mrq.el
(use-package mrq
  :load-path "~/workspace/mrq/plugin_emacs"
  :commands (mrq-setup mrq-mode)
  :hook (prog-mode . mrq-setup))
```

`mrq-setup` 은 `.mrq/current` 를 못 찾으면 조용히 빠지므로 `prog-mode-hook` 에
걸어도 안전하다. `markdown-mode` 는 당신 설정의 것을 쓴다 (`.elpa` 격리는 테스트
전용이다).

```sh
cd ~/workspace/mr-helper && mrq pull
```

---

## 기본 왕복

- [ ] 소스 파일을 열면 코멘트가 `:note` 진단으로 뜬다
- [ ] `M-g n` / `M-g p` 가 코멘트 사이를 돈다
- [ ] `C-c m r` → `review.md` 의 해당 `### reply` 로 간다
- [ ] 답글을 쓰고 저장 → `sync` 가 돌고 **커서가 그 스레드에 남는다**
- [ ] 저장 후 열린 소스 버퍼의 진단이 **자동으로** 갱신된다 (file-notify)
- [ ] `C-c C-t` 로 체크박스를 돌리고 저장 → 상태가 반영된다
- [ ] `RET` 로 목록에서 소스로, `C-c m r` 로 소스에서 목록으로 — 왕복이 닫힌다
- [ ] `g`(pull) / `r`(reanchor) 가 동작하고 버퍼가 갱신된다
- [ ] `C-c C-p` 가 status 요약을 보여주고 확인을 받는다

## 당신 설정과의 상호작용 — ERT 가 못 보는 부분

- [ ] **다른 flymake 백엔드와 공존한다.** 파이썬/elisp 버퍼에서 기존 린터 진단과
      섞여 뜨고, 어느 쪽도 사라지지 않는다. (`M-x flymake-show-buffer-diagnostics`
      로 둘 다 보이는지 확인)
- [ ] **키 바인딩이 충돌하지 않는다.** `C-h k C-c m r` 가 `mrq-reply-at-point` 를
      가리킨다. Exordium 의 기존 `C-c m` 바인딩과 겹치지 않는다
- [ ] `mrq-mode` 버퍼에서 `g` 와 `r` 이 markdown-mode 의 자기 삽입을 덮어쓰는데
      **그게 거슬리지 않는가.** 답글을 쓰는 면이기도 하므로, 글자 `g` 를 치려다
      pull 이 도는 사고가 나면 바인딩을 바꿔야 한다
- [ ] 큰 파일(수천 줄)에서 편집 중 체감 지연이 없다 — 보정은 버퍼를 통째로
      문자열 벡터로 만든다

## 관찰 항목 — 잠정 결정의 재평가

`editor.md` §3.4 는 **위치 없는 경고**를 에코 영역과 `*mrq*` 로만 보내기로 했고
그 선택을 "잠정" 으로 표시했다 (`mrq-design.md` §6). 지금 그 경고가 알리는 것은
**"답글을 썼는데 전송되지 않는다"** 이고, 놓치면 답글이 그대로 남는다.

- [ ] 답글을 쓰고 체크박스를 `[ ]` 로 **둔 채** 저장한다
- [ ] 그 경고를 **알아챘는가?** 에코 영역은 다른 메시지에 금방 덮인다
- [ ] 알아채지 못했다면 선택지: `*mrq*` 를 자동으로 띄운다 / 헤더라인에 남긴다 /
      `review.md` 안에 경고를 렌더한다. 고른 것을 `mrq-design.md` §6 에 적고
      `editor.md` §3.4 의 "잠정" 표시를 지운다

## 충돌 UI — 만들기 쉽지만 쓰기 전까지 모르는 것

터미널에서 `mrq reply <id> -m "AI 쪽"` 을 돌린 뒤 같은 스레드를 `review.md` 에서
다르게 고치면 충돌이 만들어진다. 둘 이상 만들어야 의미가 있다.

- [ ] 저장 → `*mrq conflicts*` 가 뜨고 양쪽 값이 보인다
- [ ] `m`/`j` 로 섞어 고르고 `C-c C-c` → 한 번에 해소된다
- [ ] 하나를 안 고르고 `C-c C-c` → 거부하고 그 스레드로 커서가 간다
- [ ] **양쪽 값만 보고 고를 수 있었는가?** 답글이 길면 첫 줄만 보여주는데
      그걸로 판단이 되는지

## 문제가 있으면

`*mrq*` 버퍼와 `*Messages*` 를 함께 붙여 주면 된다.
`M-x toggle-debug-on-error` 뒤 재현하면 백트레이스가 남는다.
`M-x flymake-show-buffer-diagnostics` 가 진단의 출처를 보여준다.
