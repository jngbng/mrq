;;; mrq-mode-test.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.2, `review-md.md' §3 (헤더 형식).
;; 이 파일만 `markdown-mode' 에 의존한다.

;;; Code:

(require 'ert)
(require 'compile)
(require 'mrq-mode)
(require 'mrq-test-helper)

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

(provide 'mrq-mode-test)
;;; mrq-mode-test.el ends here
