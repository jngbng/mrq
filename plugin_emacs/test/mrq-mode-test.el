;;; mrq-mode-test.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.2, `review-md.md' §3 (헤더 형식).
;; 이 파일만 `markdown-mode' 에 의존한다.

;;; Code:

(require 'ert)
(require 'compile)
(require 'mrq)
(require 'mrq-mode)
(require 'mrq-test-helper)
(require 'python)

(defconst mrq-mode-test--md
  (concat "<!-- mrq:7a0b1c2d3e4f v:000001 -->\n"
          "## [ ] (general) — @kim\n"
          "\n### reply\n\n\n"
          "<!-- mrq:a1b2c3d4e5f6 v:000002 -->\n"
          "## [ ] src/api/client.py:2 — @jdoe\n"
          "\n### reply\n\n\n")
  "블록 둘짜리 최소 `review.md' — 위치 없는 것과 있는 것.")

(defun mrq-mode-test--open (root text)
  "ROOT 의 review.md 를 TEXT 로 만들고 버퍼를 돌려준다."
  (let ((md (expand-file-name ".mrq/1234/review.md" root)))
    (write-region text nil md nil 'quiet)
    (find-file-noselect md)))

;;; 헤더 정규식 — `next-error' 와 `RET' 이 같은 정의를 써야 한다

(ert-deftest mrq-mode-header-re-matches-a-located-header ()
  (let ((line "## [ ] src/api/client.py:102 — @jdoe"))
    (should (string-match mrq-mode-header-re line))
    (should (equal (match-string 1 line) "src/api/client.py"))
    (should (equal (match-string 2 line) "102"))))

(ert-deftest mrq-mode-header-re-matches-every-state-char ()
  (dolist (char '(" " "x" "~" "-"))
    (should (string-match mrq-mode-header-re
                          (format "## [%s] a/b.py:1 — @x" char)))))

(ert-deftest mrq-mode-header-re-ignores-general-headers ()
  "의도된 동작이다 (`review-md.md' §3) — 위치가 없는 코멘트다.

가짜 위치로 점프시키면 위치 신뢰를 잃는다."
  (should-not (string-match mrq-mode-header-re "## [ ] (general) — @kim")))

(ert-deftest mrq-mode-header-re-ignores-reply-sections-and-prose ()
  (should-not (string-match mrq-mode-header-re "### reply"))
  (should-not (string-match mrq-mode-header-re "본문에 src/a.py:1 이 있어도"))
  (should-not (string-match mrq-mode-header-re "# !1234 Add retry logic")))

(ert-deftest mrq-mode-header-re-is-the-one-compilation-entry ()
  "정의가 둘로 갈라지면 `M-g n' 과 `RET' 이 다른 데로 간다."
  (should (equal (cadr (assq 'mrq compilation-error-regexp-alist-alist))
                 mrq-mode-header-re)))

;;; 체크박스 — 문자 치환일 뿐이다

(ert-deftest mrq-mode-toggles-the-checkbox-in-a-cycle ()
  "의미는 `sync' 가 준다 (`editor.md' §1)."
  (with-temp-buffer
    (insert mrq-mode-test--md)
    (delay-mode-hooks (mrq-mode))
    (dolist (want '("x" "~" "-" " "))
      (goto-char (point-min))
      (search-forward "### reply")            ; 첫 블록의 reply 영역 안
      (mrq-mode-toggle-state)
      (goto-char (point-min))
      (should (search-forward (format "## [%s] (general)" want) nil t)))))

(ert-deftest mrq-mode-toggles-the-block-point-is-in-not-the-first ()
  (with-temp-buffer
    (insert mrq-mode-test--md)
    (delay-mode-hooks (mrq-mode))
    (goto-char (point-min))
    (search-forward "<!-- mrq:a1b2c3d4e5f6")
    (search-forward "### reply")
    (mrq-mode-toggle-state)
    (goto-char (point-min))
    (should (search-forward "## [x] src/api/client.py:2" nil t))
    (goto-char (point-min))
    (should (search-forward "## [ ] (general)" nil t))))

(ert-deftest mrq-mode-toggle-outside-a-block-is-a-user-error ()
  (with-temp-buffer
    (insert "# !1234 제목\n\n본문\n")
    (delay-mode-hooks (mrq-mode))
    (goto-char (point-min))
    (should-error (mrq-mode-toggle-state) :type 'user-error)))

;;; RET — 경로는 리포 상대다

(ert-deftest mrq-mode-visit-opens-the-source-relative-to-the-repo-root ()
  "`review.md' 는 `.mrq/<iid>/' 에 있으므로 `default-directory' 기준으로 풀면
엉뚱한 곳을 연다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\n")))
    (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
      (goto-char (point-min))
      (search-forward "## [ ] src/api/client.py:2")
      (mrq-mode-visit)
      (should (equal (file-truename (buffer-file-name))
                     (file-truename (expand-file-name "src/api/client.py" root))))
      (should (= (line-number-at-pos) 2)))))

(ert-deftest mrq-mode-visit-on-a-general-header-is-a-user-error ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\n")))
    (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
      (goto-char (point-min))
      (search-forward "## [ ] (general)")
      (should-error (mrq-mode-visit) :type 'user-error))))

(ert-deftest mrq-mode-visit-reports-a-missing-source-file ()
  (mrq-test-with-repo (root)
    (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
      (goto-char (point-min))
      (search-forward "## [ ] src/api/client.py:2")
      (should-error (mrq-mode-visit) :type 'user-error))))

;;; next-error

(ert-deftest mrq-mode-next-error-walks-located-headers-only ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\n")))
    (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
      (goto-char (point-min))
      (mrq-mode-next-error 1 t)
      ;; `(general)` 을 건너뛰고 client.py 로 간다
      (should (equal (file-truename (buffer-file-name))
                     (file-truename (expand-file-name "src/api/client.py" root)))))))

(ert-deftest mrq-mode-next-error-past-the-last-is-a-user-error ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\n")))
    (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
      (goto-char (point-max))
      (should-error (mrq-mode-next-error 1 nil) :type 'user-error))))

;;; 모드 등록

(ert-deftest mrq-mode-is-the-major-mode-for-a-review-md ()
  (mrq-test-with-repo (root)
    (let ((md (expand-file-name ".mrq/1234/review.md" root)))
      (write-region "# !1234 t\n" nil md nil 'quiet)
      (with-current-buffer (find-file-noselect md)
        (should (eq major-mode 'mrq-mode))))))

(ert-deftest mrq-mode-does-not-claim-other-review-md-files ()
  (mrq-test-with-repo (root)
    (let ((other (expand-file-name "docs/review.md" root)))
      (make-directory (expand-file-name "docs" root) t)
      (write-region "# hi\n" nil other nil 'quiet)
      (with-current-buffer (find-file-noselect other)
        (should-not (eq major-mode 'mrq-mode))))))

(ert-deftest mrq-mode-derives-from-markdown-mode ()
  "표·코드펜스가 섞인 답글을 쓰는 면이므로 markdown 편집이 그대로 있어야 한다."
  (with-temp-buffer
    (delay-mode-hooks (mrq-mode))
    (should (derived-mode-p 'markdown-mode))))

;;; 저장 훅과 종료 코드 분기

(defconst mrq-mode-test--ok-json
  (concat "{\"iid\":1234,\"applied\":[],\"warnings\":[],"
          "\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}")
  "`sync --json' 의 exit 0 페이로드.")

(ert-deftest mrq-mode-save-runs-sync ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "확인했습니다.\n")
        (save-buffer)
        (should (equal (mrq-test-cli-calls root) '("sync --json")))))))

(ert-deftest mrq-mode-does-nothing-on-saving-a-source-file ()
  "`editor.md' §3.3 — 소스 저장에는 아무것도 하지 않는다.

매번 재앵커링을 돌리면 json 과 md 를 다시 쓰게 되는데 그 비용을 낼 이유가 없다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root)))
      (with-current-buffer (find-file-noselect
                            (expand-file-name "src/api/client.py" root))
        (goto-char (point-max))
        (insert "c\n")
        (save-buffer)
        (should (null (mrq-test-cli-calls root)))))))

(ert-deftest mrq-mode-save-restores-point-by-thread-id-not-line ()
  "`sync' 가 `review.md' 를 재렌더한다 (`cli.md' §5 5단계).

줄 번호로 복원하면 앞 블록의 길이가 바뀔 때마다 커서가 흘러간다 — 답글을
쓸 때마다 일어나는 일이다.  가짜 `mrq' 가 진짜처럼 md 를 다시 쓴다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let* ((md (expand-file-name ".mrq/1234/review.md" root))
           (grown (replace-regexp-in-string
                   "## \\[ \\] (general) — @kim\n"
                   "## [ ] (general) — @kim\n\n> 서버가 덧붙인 줄\n> 또 한 줄\n"
                   mrq-mode-test--md t t))
           (mrq-executable (mrq-test-fake-cli root
                                              :stdout mrq-mode-test--ok-json
                                              :writes (cons md grown))))
      (should-not (equal grown mrq-mode-test--md))   ; 픽스처가 실제로 늘었는가
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-min))
        (search-forward "<!-- mrq:a1b2c3d4e5f6")
        (search-forward "### reply")
        (forward-line 1)
        (insert "답글 한 줄\n")
        ;; `before' 는 **삽입 뒤**에 잡는다.  삽입 전에 잡으면 줄 번호로
        ;; 복원하는 구현도 "줄이 늘었다" 를 만족해 테스트가 가짜로 통과한다.
        (let ((before (line-number-at-pos)))
          (save-buffer)
          (should (string-match-p "서버가 덧붙인 줄" (buffer-string)))
          ;; 앞 블록이 세 줄 늘었으므로 줄 번호는 커지고, 스레드는 그대로다
          (should (> (line-number-at-pos) before))
          (should (equal (save-excursion
                           (re-search-backward mrq-mode-anchor-re nil t)
                           (match-string 1))
                         "a1b2c3d4e5f6")))))))

(ert-deftest mrq-mode-parse-error-does-not-revert-the-buffer ()
  "exit 2 — CLI 가 아무것도 안 썼고 고칠 내용이 지금 버퍼에 있다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli
            root :code 2
            :stdout (concat "{\"errors\":[{\"line\":8,"
                            "\"message\":\"체크박스 문자를 해석할 수 없음\"}]}"))))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "내가 쓴 것\n")
        (save-buffer)
        ;; 저장은 됐고(디스크에도 있고) 되읽지 않았으므로 버퍼에 그대로 있다
        (should (string-match-p "내가 쓴 것" (buffer-string)))
        (with-current-buffer "*mrq*"
          (should (string-match-p "review.md:8: 체크박스" (buffer-string))))))))

(ert-deftest mrq-mode-logs-a-warning-without-a-line-without-inventing-one ()
  "`cli.md' §5 MUST NOT — `review.md:0' 도 1 행도 쓰지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli
            root
            :stdout (concat "{\"iid\":1234,\"applied\":[],\"warnings\":"
                            "[{\"line\":null,\"message\":"
                            "\"a1b2c3d4: 답글이 있는데 상태가 todo 입니다\"}],"
                            "\"anchors\":{\"exact\":1,\"fuzzy\":0,\"stale\":0}}"))))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "답글\n")                      ; 수정해야 save-buffer 가 돈다
        (save-buffer)
        (with-current-buffer "*mrq*"
          (let ((text (buffer-string)))
            (should (string-match-p "답글이 있는데" text))
            (should-not (string-match-p "review.md:0" text))
            (should-not (string-match-p "review.md:1:" text))))))))

(ert-deftest mrq-mode-mrq-buffer-is-a-compilation-buffer ()
  "`review.md:142:' 가 그대로 `C-x `' 로 점프 가능해야 한다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli root :code 2
                              :stdout "{\"errors\":[{\"line\":3,\"message\":\"x\"}]}")))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "답글\n")
        (save-buffer)
        (with-current-buffer "*mrq*"
          (should (derived-mode-p 'compilation-mode))
          ;; 상대 경로 `review.md' 가 풀리도록 리뷰 디렉터리가 기준이어야 한다
          (should (file-exists-p (expand-file-name "review.md" default-directory))))))))

(ert-deftest mrq-mode-reanchor-and-pull-use-the-cli ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (mrq-mode-reanchor)
        (mrq-mode-pull)
        (should (equal (mrq-test-cli-calls root)
                       '("reanchor --json" "pull")))))))

(ert-deftest mrq-mode-push-asks-before-sending ()
  "되돌릴 수 없는 작업이므로 확인을 받는다 (`editor.md' §3.2)."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (cl-letf (((symbol-function 'yes-or-no-p) (lambda (&rest _) nil)))
          (mrq-mode-push))
        ;; 거절했으므로 status 만 돌고 push 는 안 나갔다
        (should (equal (mrq-test-cli-calls root) '("status --json")))
        (cl-letf (((symbol-function 'yes-or-no-p) (lambda (&rest _) t)))
          (mrq-mode-push))
        (should (equal (mrq-test-cli-calls root)
                       '("status --json" "status --json" "push --json")))))))

(ert-deftest mrq-mode-reports-a-generic-failure-without-reverting ()
  "exit 1/5/6/7 — stderr 를 보여주고 멈춘다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli root :code 7
                              :stderr "review.json 의 schema_version 이 99 입니다\n")))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (should-error (mrq-mode-sync) :type 'user-error)
        (with-current-buffer "*mrq*"
          (should (string-match-p "schema_version" (buffer-string))))))))

;;; mrq-reply-at-point — 소스 <-> 목록 왕복을 닫는다

(ert-deftest mrq-reply-at-point-jumps-to-the-reply-section ()
  "`review.md' 에서 앵커를 **검색**하는 것은 파싱이 아니다 (`editor.md' §1).

상태나 답글을 추출하지 않고 점만 옮긴다 — 틀려야 커서가 엉뚱한 데 가고
사용자가 즉시 본다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (write-region mrq-mode-test--md nil
                  (expand-file-name ".mrq/1234/review.md" root) nil 'quiet)
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (mrq-setup)
      (flymake-start nil t)
      (let ((diag (car (flymake-diagnostics))))
        (should diag)
        (goto-char (flymake-diagnostic-beg diag)))
      (mrq-reply-at-point)
      (should (equal (file-name-nondirectory (buffer-file-name)) "review.md"))
      ;; a1b2 블록의 `### reply' 아래에 있다
      (should (equal (save-excursion
                       (re-search-backward mrq-mode-anchor-re nil t)
                       (match-string 1))
                     "a1b2c3d4e5f6"))
      (should (save-excursion
                (re-search-backward "^### reply$" nil t))))))

(ert-deftest mrq-reply-at-point-errors-without-a-diagnostic ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\n")))
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (should-error (mrq-reply-at-point) :type 'user-error))))

(ert-deftest mrq-reply-at-point-errors-without-a-review-md ()
  "`review.md' 가 없으면 `mrq pull --render' 를 안내한다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\nc\nd\ne\n")))
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (mrq-setup)
      (flymake-start nil t)
      (goto-char (flymake-diagnostic-beg (car (flymake-diagnostics))))
      (should-error (mrq-reply-at-point) :type 'user-error))))

(ert-deftest mrq-setup-is-a-noop-outside-a-review-repo ()
  "`prog-mode-hook' 에 걸어도 안전해야 한다."
  (let ((dir (file-truename (make-temp-file "mrq-bare-" t))))
    (unwind-protect
        (let ((file (expand-file-name "a.py" dir)))
          (write-region "x\n" nil file nil 'quiet)
          (with-current-buffer (find-file-noselect file)
            (mrq-setup)
            (should-not (bound-and-true-p flymake-mode))
            (kill-buffer)))
      (delete-directory dir t))))

;;; 편집면 안전 — C1·C2·I9

(ert-deftest mrq-mode-plain-letters-insert-themselves ()
  "`review.md' 는 답글을 쓰는 **편집 버퍼**다.

평문 `r'/`g' 를 명령에 묶으면 \"retry 로직을 고쳤습니다\" 의 첫 글자가
`mrq reanchor' 를 돌린다."
  (with-temp-buffer
    (delay-mode-hooks (mrq-mode))
    (dolist (key '("r" "g" "m" "j" "n" "p" "q"))
      (should (eq (key-binding (kbd key)) #'self-insert-command)))))

(ert-deftest mrq-mode-sync-saves-first-instead-of-discarding-edits ()
  "`C-c C-s' 가 미저장 답글을 버리면 안 된다.

`sync' 는 **디스크의 md** 를 읽으므로, 저장하지 않고 부르면 CLI 가 옛 내용을
반영하고 재렌더가 작성 중인 답글을 덮어쓴다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "작성 중인 답글\n")
        (should (buffer-modified-p))
        (mrq-mode-sync)
        (should (string-match-p "작성 중인 답글" (buffer-string)))
        (should-not (buffer-modified-p))
        ;; 저장이 저장 훅을 통해 sync 를 한 번만 돌렸다
        (should (equal (mrq-test-cli-calls root) '("sync --json")))))))

(ert-deftest mrq-mode-reanchor-refuses-while-the-buffer-is-modified ()
  "`reanchor' 와 `pull' 은 md 를 다시 쓴다 — 미저장 편집 위에 돌리면 지워진다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "작성 중인 답글\n")
        (should-error (mrq-mode-reanchor) :type 'user-error)
        (should-error (mrq-mode-pull) :type 'user-error)
        (should-error (mrq-mode-push) :type 'user-error)
        (should (string-match-p "작성 중인 답글" (buffer-string)))
        (should (null (mrq-test-cli-calls root)))
        (set-buffer-modified-p nil)))))

(ert-deftest mrq-mode-refuses-to-sync-a-review-md-that-is-not-current ()
  "`sync' 에는 `--mr' 이 없다 (`cli.md' §1).

`.mrq/3/review.md' 를 저장하면 `current' 가 가리키는 **다른 MR** 이 sync 된다 —
MR 3 의 답글은 디스크에만 남고 다음 재렌더에 사라진다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((other (expand-file-name ".mrq/3" root))
          (mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (make-directory other t)
      (write-region (mrq-test-sample-review) nil
                    (expand-file-name "review.json" other) nil 'quiet)
      (write-region mrq-mode-test--md nil
                    (expand-file-name "review.md" other) nil 'quiet)
      (with-current-buffer (find-file-noselect (expand-file-name "review.md" other))
        (should (eq major-mode 'mrq-mode))
        (goto-char (point-max))
        (insert "MR 3 에 쓴 답글\n")
        (should-error (save-buffer) :type 'user-error)
        (should (null (mrq-test-cli-calls root)))
        (set-buffer-modified-p nil)))))

(ert-deftest mrq-mode-push-prompt-shows-the-status-summary ()
  "되돌릴 수 없는 전송을 검토면 없이 승인하게 하면 안 된다.

`status --json' 의 요약은 **stdout** 으로 나온다 (`cli.md' §2) — stderr 를
프롬프트에 붙이면 빈 문자열이 뜬다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli
            root
            :stdout (concat "{\"iid\":1234,\"push\":{\"replies\":4,\"resolves\":3,"
                            "\"skipped\":1},\"anchors\":{\"exact\":12,\"fuzzy\":2,"
                            "\"stale\":1}}")))
          (prompt nil))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (cl-letf (((symbol-function 'yes-or-no-p)
                   (lambda (text) (setq prompt text) nil)))
          (mrq-mode-push))
        (should (string-match-p "4" prompt))
        (should (string-match-p "3" prompt))))))

(ert-deftest mrq-setup-does-not-pollute-the-major-mode-map ()
  "`local-set-key' 는 현재 로컬 맵을 **그 자리에서** 고친다 — 그 맵이 곧
메이저 모드 맵이다.

`prog-mode-hook' 에 걸고 리뷰 리포의 .py 를 한 번 열면, 그 세션의 **모든**
python 버퍼(리뷰와 무관한 다른 프로젝트 포함)에서 `C-c m' 이 mrq 에 묶인다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (mrq-setup)
      (should (eq (key-binding (kbd "C-c m r")) #'mrq-reply-at-point)))
    ;; 같은 메이저 모드의 무관한 버퍼
    (with-temp-buffer
      (delay-mode-hooks (python-mode))
      (should-not (eq (key-binding (kbd "C-c m r")) #'mrq-reply-at-point)))))

(ert-deftest mrq-flymake-refresh-actually-updates-an-open-buffer ()
  "§1-5 MUST 의 end-to-end — AI 가 `mrq reply' 로 json 을 고치는 동안
사용자의 버퍼가 갱신돼야 한다.

훅이 불렸는지만 보면 `mrq-flymake-refresh' 의 버퍼 선별(truename 정규화 포함)이
틀려도 통과한다."
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                               (mrq-flymake-test--lines 320))))
    (let ((file (expand-file-name "src/api/client.py" root)))
      (with-current-buffer (find-file-noselect file)
        (mrq-flymake-setup)
        (flymake-start nil t)
        (should (= (length (flymake-diagnostics)) 1))
        ;; AI 가 그 스레드를 처리한 것처럼 json 을 바꾼다 -> 기본 보기에서 사라진다
        (mrq-test-write-review
         root 1234
         (replace-regexp-in-string
          "\"state\": \"todo\"" "\"state\": \"done\"" (mrq-test-sample-review) t t))
        (should (mrq-test-wait-for (lambda () (null (flymake-diagnostics)))))))))

(provide 'mrq-mode-test)
;;; mrq-mode-test.el ends here
