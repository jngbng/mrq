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
(require 'mrq-boundary-test)
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

(ert-deftest mrq-mode-pull-uses-the-cli ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (mrq-mode-pull)
        (should (equal (mrq-test-cli-calls root) '("pull")))))))

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
  ;; 짧은 버퍼에서는 102행·7행이 모두 마지막 줄로 clamp 돼 flymake 가 같은
  ;; 영역의 오버레이를 합친다 — 두 스레드가 다른 줄에 앉도록 길게 만든다.
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                               (mrq-flymake-test--lines 320))))
    (write-region mrq-mode-test--md nil
                  (expand-file-name ".mrq/1234/review.md" root) nil 'quiet)
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (mrq-setup)
      (flymake-start nil t)
      ;; client.py 에는 진단이 둘이다 (a1b2 미처리, d4e5 미전송 답글).
      ;; md 픽스처에 블록이 있는 a1b2 를 지목한다.
      (let ((diag (seq-find (lambda (d) (equal (flymake-diagnostic-data d)
                                               "a1b2c3d4e5f6"))
                            (flymake-diagnostics))))
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

(ert-deftest mrq-mode-pull-refuses-while-the-buffer-is-modified ()
  "`pull' 과 `push' 는 md 를 다시 쓴다 — 미저장 편집 위에 돌리면 지워진다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json)))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "작성 중인 답글\n")
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
        (should (= (length (flymake-diagnostics)) 2))
        ;; 전부 **닫힌** 것처럼 json 을 바꾼다 (내가 건너뜀 + 답글 비움)
        ;; -> 기본 보기에서 사라진다
        (mrq-test-write-review
         root 1234
         (replace-regexp-in-string
          "\"reply\": \"[^\"]*\"" "\"reply\": \"\""
          (replace-regexp-in-string "\"state\": \"[a-z]+\"" "\"state\": \"skipped\""
                                    (mrq-test-sample-review) t t)
          t t))
        (should (mrq-test-wait-for (lambda () (null (flymake-diagnostics)))))))))

(ert-deftest mrq-minor-mode-binds-flymake-navigation ()
  "flymake 는 `flymake-goto-next-error' 에 **기본 바인딩을 주지 않는다**
\(`flymake-mode-map' 에는 메뉴바와 fringe 뿐이다, 실측).

`editor.md' §3.1 은 \"그 명령이 그대로 다음 코멘트 이동이 된다\" 고 하지만,
누를 키가 없으면 그 문장은 닿지 않는다.  `next-error' 로도 안 된다 —
`flymake-mode' 는 소스 버퍼에서 `next-error-function' 을 설정하지 않는다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (with-current-buffer (find-file-noselect
                          (expand-file-name "src/api/client.py" root))
      (mrq-setup)
      (should (eq (key-binding (kbd "C-c m n")) #'flymake-goto-next-error))
      (should (eq (key-binding (kbd "C-c m p")) #'flymake-goto-prev-error)))
    (with-temp-buffer
      (delay-mode-hooks (python-mode))
      (should-not (eq (key-binding (kbd "C-c m n")) #'flymake-goto-next-error)))))

(ert-deftest mrq-keymaps-survive-a-reload ()
  "`eval-buffer'/`load-library' 로 고친 바인딩이 반영돼야 한다.

`defvar' 는 이미 값이 있으면 초기화 폼을 **평가하지 않는다** — 키맵을
`defvar' 의 초기값으로 만들면 재로드가 아무 효과가 없고, 사용자는 Emacs 를
껐다 켜야 한다.  게다가 `mrq-minor-mode-map' 과 `minor-mode-map-alist' 는
키맵 **객체**를 들고 있으므로 변수에 새 객체를 넣어도 닿지 않는다.

그래서 키맵은 빈 채로 `defvar' 하고 `define-key' 를 최상위에서 부른다 —
객체는 그대로 두고 내용만 바꾼다."
  (let ((file (expand-file-name "mrq.el" mrq-boundary-test--src-dir))
        (command-map mrq-command-map)
        (minor-map mrq-minor-mode-map))
    ;; 옛 버전처럼 바인딩 하나를 지운다
    (define-key mrq-command-map (kbd "n") nil)
    (should-not (lookup-key mrq-command-map (kbd "n")))
    (load file nil t)
    (should (eq (lookup-key mrq-command-map (kbd "n")) #'flymake-goto-next-error))
    ;; 객체가 바뀌지 않았다 — minor-mode-map-alist 가 여전히 유효하다
    (should (eq mrq-command-map command-map))
    (should (eq mrq-minor-mode-map minor-map))
    (should (eq (lookup-key mrq-minor-mode-map (kbd "C-c m")) mrq-command-map))))

(ert-deftest mrq-mode-leaves-ret-to-markdown ()
  "`review.md' 는 편집면이다 — `RET' 는 markdown 의 것이어야 한다.

소스 점프는 `C-c m r' 로 옮겼다.  문맥에 따라 갈라지는 `RET' 는 설명하기도
어렵고 틀리기도 쉬웠다."
  (with-temp-buffer
    (insert mrq-mode-test--md)
    (delay-mode-hooks (mrq-mode))
    (should (eq (key-binding (kbd "RET"))
                (lookup-key markdown-mode-map (kbd "RET"))))))

(ert-deftest mrq-mode-keeps-markdown-prefixes ()
  "`C-c C-s'(스타일)와 `C-c C-t'(제목)는 markdown 의 가장 쓸모 있는 접두사다.

답글에 코드펜스·표·굵게를 넣는 경로라 (`review-md.md' §1) 가리면 안 된다."
  (with-temp-buffer
    (insert mrq-mode-test--md)
    (delay-mode-hooks (mrq-mode))
    (dolist (key '("C-c C-s" "C-c C-t"))
      (should (keymapp (key-binding (kbd key)))))
    (should (eq (key-binding (kbd "C-c C-s C")) #'markdown-insert-gfm-code-block))
    (should (eq (key-binding (kbd "C-c C-s t")) #'markdown-insert-table))
    (should (eq (key-binding (kbd "C-c C-p")) #'markdown-outline-previous))))

(ert-deftest mrq-mode-commands-live-under-the-c-c-m-prefix ()
  "소스 버퍼와 같은 접두사를 쓴다 — 외울 것이 하나다."
  (with-temp-buffer
    (insert mrq-mode-test--md)
    (delay-mode-hooks (mrq-mode))
    (should (eq (key-binding (kbd "C-c m s")) #'mrq-mode-sync))
    (should (eq (key-binding (kbd "C-c m p")) #'mrq-mode-push))
    (should (eq (key-binding (kbd "C-c m f")) #'mrq-mode-pull))
    (should (eq (key-binding (kbd "C-c m t")) #'mrq-mode-toggle-state))
    (should (eq (key-binding (kbd "C-c m r")) #'mrq-mode-visit))))

(ert-deftest mrq-mode-has-no-reanchor-command ()
  "reanchor 가 필요한 곳은 소스 버퍼다 (`C-c m R').

`review.md' 를 편집하는 동안 소스는 바뀌지 않고, 저장하면 `sync' 가 어차피
재앵커링을 포함한다 (`cli.md' §5 4단계)."
  (should-not (fboundp 'mrq-mode-reanchor)))

(ert-deftest mrq-reanchor-runs-from-a-source-buffer ()
  "소스를 고치고 저장한 뒤 위치를 다시 잡는 경로."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli
            root :stdout "{\"anchors\":{\"exact\":12,\"fuzzy\":2,\"stale\":1}}")))
      (with-current-buffer (find-file-noselect
                            (expand-file-name "src/api/client.py" root))
        (mrq-setup)
        (should (eq (key-binding (kbd "C-c m R")) #'mrq-reanchor))
        (call-interactively #'mrq-reanchor)
        (should (equal (mrq-test-cli-calls root) '("reanchor --json")))
        ;; 소스 버퍼를 되읽지 않는다 — review.json 변경은 watch 가 처리한다
        (should (equal (file-name-nondirectory (buffer-file-name)) "client.py"))))))

(ert-deftest mrq-reply-at-point-opens-review-md-in-the-same-window ()
  "다른 윈도우에 열면 배치가 틀어져 혼란스럽다.

소스 -> review.md -> (C-c m r) -> 소스 가 같은 창에서 오간다."
  (mrq-test-with-repo (root :files (list (cons "src/api/client.py"
                                               (mrq-flymake-test--lines 320))))
    (write-region mrq-mode-test--md nil
                  (expand-file-name ".mrq/1234/review.md" root) nil 'quiet)
    (let* ((source (find-file-noselect (expand-file-name "src/api/client.py" root)))
           (other (get-buffer-create "*다른 창*")))
      (delete-other-windows)
      (set-window-buffer (selected-window) source)
      (let ((here (selected-window)))
        (set-window-buffer (split-window) other)
        (select-window here)
        (with-current-buffer source
          (mrq-setup)
          (flymake-start nil t)
          (goto-char (flymake-diagnostic-beg
                      (seq-find (lambda (d) (equal (flymake-diagnostic-data d)
                                                   "a1b2c3d4e5f6"))
                                (flymake-diagnostics))))
          (mrq-reply-at-point))
        ;; 내가 있던 창이 review.md 를 보여준다
        (should (equal (file-name-nondirectory
                        (buffer-file-name (window-buffer here)))
                       "review.md"))
        ;; 옆 창은 그대로다
        (should (eq (window-buffer (next-window here)) other)))
      (delete-other-windows)
      (kill-buffer other))))

(defun mrq-mode-test--save-with-render (root rendered)
  "RENDERED 로 재렌더하는 가짜 `mrq' 를 꽂고 저장한 뒤 (저장전 . 저장후) 줄."
  (let* ((md (expand-file-name ".mrq/1234/review.md" root))
         (mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json
                                            :writes (cons md rendered))))
    (write-region mrq-mode-test--md nil md nil 'quiet)
    (with-current-buffer (find-file-noselect md)
      (goto-char (point-min))
      (search-forward "<!-- mrq:a1b2c3d4e5f6")
      (search-forward "### reply")
      (forward-line 1)
      (insert "답글 첫 줄\n답글 둘째 줄\n")
      (let ((before (line-number-at-pos)))
        (save-buffer)
        (cons before (line-number-at-pos))))))

(ert-deftest mrq-mode-point-stays-inside-the-block-when-it-shrinks ()
  "재렌더가 블록을 줄이면 오프셋이 **다음 스레드로 흘러간다.**

`sync' 는 답글을 정규형으로 다시 쓰므로(`render.normalize_reply') 사용자가
친 빈 줄이 사라지는 것이 정상 경로다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((shrunk (replace-regexp-in-string "### reply\n\n\n" "### reply\n"
                                            mrq-mode-test--md t t)))
      (mrq-mode-test--save-with-render root shrunk)
      (with-current-buffer (find-buffer-visiting
                            (expand-file-name ".mrq/1234/review.md" root))
        ;; 여전히 a1b2 블록 안이다 — 앞 블록으로도 뒤 블록으로도 넘어가지 않았다
        (should (equal (car (mrq-mode--thread-at-point)) "a1b2c3d4e5f6"))))))

(ert-deftest mrq-mode-point-does-not-jump-to-the-top-when-the-block-vanishes ()
  "서버에서 resolve 된 스레드는 재렌더가 생략한다 (`review-md.md' §5).

그때 앵커를 못 찾는다고 **버퍼 맨 처음**으로 보내면, 답글을 쓰던 사용자가
문서 꼭대기로 튕긴다.  있던 자리 근처가 낫다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let* ((gone (replace-regexp-in-string
                  "<!-- mrq:a1b2c3d4e5f6 v:000002 -->\n## \\[ \\] src/api/client.py:2 — @jdoe\n\n### reply\n\n\n"
                  "" mrq-mode-test--md t t))
           (lines (mrq-mode-test--save-with-render root gone)))
      (should-not (equal gone mrq-mode-test--md))   ; 픽스처가 실제로 지워졌는가
      (should (> (cdr lines) 1)))))

(ert-deftest mrq-reply-at-point-works-anywhere-on-the-line ()
  "진단 영역은 **첫 비공백**에서 시작한다 (`flymake-diag-region').

소스 코드는 들여쓰기가 있는 것이 보통이라, 줄 맨 앞에서 `C-c m r' 을 누르면
\"여기에 MR 코멘트가 없습니다\" 가 떴다.  반대 방향(`review.md' -> 소스)은
줄 맨 앞으로 보내므로 동작이 쌍이 맞지 않았다."
  (let ((anchor (mrq-flymake-test--anchor-line "f6a1b2c3d4e5"))
        (line (mrq-flymake-test--location-line "f6a1b2c3d4e5")))
    (should (string-prefix-p " " anchor))      ; 들여쓰기가 있는 줄인가
    (mrq-test-with-repo (root :files (list (cons "src/api/retry.py"
                                                 (mrq-flymake-test--filler line anchor))))
      (write-region (concat "<!-- mrq:f6a1b2c3d4e5 v:000001 -->\n"
                            "## [ ] src/api/retry.py:14 — @x\n\n### reply\n\n")
                    nil (expand-file-name ".mrq/1234/review.md" root) nil 'quiet)
      (with-current-buffer (find-file-noselect
                            (expand-file-name "src/api/retry.py" root))
        (mrq-setup)
        (flymake-start nil t)
        (goto-char (flymake-diagnostic-beg (car (flymake-diagnostics))))
        (beginning-of-line)                     ; 들여쓰기 **앞**
        (should (= (current-column) 0))
        (should (equal (mrq-flymake-thread-at-point) "f6a1b2c3d4e5"))
        (mrq-reply-at-point)
        (should (equal (file-name-nondirectory (buffer-file-name)) "review.md"))))))

(ert-deftest mrq-log-buffer-can-jump-to-the-reported-line ()
  "`*mrq*' 에서 `RET' 이 \"No error here\" 만 뜨면 경고를 보여줄 이유가 없다.

`review.md:142: ...' 를 잡는 정규식이 필요하다 — `mrq' 항목은 `review.md' 의
**헤더**(`## [x] path:line')용이라 로그 줄을 못 잡는다."
  (require 'compile)
  (let ((entry (assq 'mrq-log compilation-error-regexp-alist-alist)))
    (should entry)
    (let ((re (cadr entry))
          (line "review.md:142: 앵커 다음 줄이 헤더가 아님"))
      (should (string-match re line))
      (should (equal (match-string 1 line) "review.md"))
      (should (equal (match-string 2 line) "142"))
      ;; 위치 없는 경고는 접두사가 없으므로 잡히면 안 된다
      (should-not (string-match re "a1b2c3d4: 답글이 있는데 상태가 todo 입니다")))))

(ert-deftest mrq-log-buffer-uses-the-log-regexp-not-the-header-one ()
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "a\nb\n")))
    (let ((mrq-executable
           (mrq-test-fake-cli
            root :code 2
            :stdout "{\"errors\":[{\"line\":3,\"message\":\"체크박스 문자\"}]}")))
      (with-current-buffer (mrq-mode-test--open root mrq-mode-test--md)
        (goto-char (point-max))
        (insert "답글\n")
        (save-buffer)
        (with-current-buffer mrq-mode-buffer-name
          (should (equal compilation-error-regexp-alist '(mrq-log)))
          (goto-char (point-min))
          (should (re-search-forward "review\\.md:3:" nil t)))))))

(ert-deftest mrq-mode-save-keeps-the-scroll-position ()
  "point 가 맞아도 **화면이 맨 위로 튀면** 답글을 쓰던 자리를 잃는다.

복원이 `point-min' 을 거쳐 가면 window-start 가 끌려간다.  point 와 화면의
상대 위치를 함께 복원해야 한다."
  (let* ((blocks (mapconcat
                  (lambda (i)
                    (format (concat "<!-- mrq:%012x v:%06x -->\n"
                                    "## [ ] src/a.py:%d — @x\n\n### reply\n\n\n")
                            (+ #xa1b200000000 i) i (1+ i)))
                  (number-sequence 1 40) ""))
         (grown (replace-regexp-in-string "v:000001" "v:0000ff" blocks t t)))
    (mrq-test-with-repo (root :files '(("src/a.py" . "x\n")))
      (let* ((md (expand-file-name ".mrq/1234/review.md" root))
             (mrq-executable (mrq-test-fake-cli root :stdout mrq-mode-test--ok-json
                                                :writes (cons md grown))))
        (write-region blocks nil md nil 'quiet)
        (with-current-buffer (find-file-noselect md)
          (set-window-buffer (selected-window) (current-buffer))
          (goto-char (point-min))
          (search-forward "<!-- mrq:a1b200000020")
          (search-forward "### reply")
          (forward-line 1)
          (recenter 5)
          (should (> (line-number-at-pos (window-start)) 1))   ; 실제로 스크롤된 상태인가
          (insert "답글\n")
          ;; `above' 는 **저장 직전**에 잰다 — 보존해야 하는 것이 그 상태다
          (let ((start (line-number-at-pos (window-start)))
                (above (count-lines (window-start) (point))))
            (save-buffer)
            ;; 화면이 맨 위로 튀지 않았다
            (should (> (line-number-at-pos (window-start)) 1))
            ;; 화면 위치가 거의 그대로이고, point 가 창 안에 있다
            (should (< (abs (- (line-number-at-pos (window-start)) start)) 3))
            (should (< (abs (- (count-lines (window-start) (point)) above)) 3))
            (should (>= (point) (window-start)))))))))

(ert-deftest mrq-mode-visit-lands-where-the-diagnostic-starts ()
  "줄 맨 앞이 아니라 **첫 비공백**으로 간다.

`review.json` 에는 열 정보가 없다 (GitLab 위치 코멘트가 줄 단위다).  진단의
시작 열은 `flymake-diag-region' 이 만드는 값이고 그게 곧 첫 비공백이라,
`back-to-indentation' 이 밑줄의 시작과 정확히 맞는다."
  (mrq-test-with-repo (root :files '(("src/api/client.py" . "def f():\n    x = 1\n")))
    (with-current-buffer (mrq-mode-test--open
                          root
                          (concat "<!-- mrq:a1b2c3d4e5f6 v:000002 -->\n"
                                  "## [ ] src/api/client.py:2 — @jdoe\n\n### reply\n\n"))
      (goto-char (point-min))
      (search-forward "## [ ] src/api/client.py:2")
      (mrq-mode-visit)
      (should (= (line-number-at-pos) 2))
      (should (= (current-column) 4))
      ;; flymake 가 밑줄을 긋는 자리와 같은가
      (should (= (point) (car (flymake-diag-region (current-buffer) 2)))))))

(provide 'mrq-mode-test)
;;; mrq-mode-test.el ends here
