;;; mrq-schema-test.el --- testdata/review/*.json 교차 검증 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `repo-layout.md' §4.2 — 세 구현이 같은 샘플을 읽을 수 있어야 한다.  Emacs 는
;; 최소한 필수 필드와 enum 값을 확인한다.
;;
;; 별도 검증기를 두지 않고 **실제 리더(`mrq-core')로 통과시키는** 이유는,
;; 잡으려는 드리프트가 "CLI 가 쓴 것을 에디터가 못 읽는 것" 이기 때문이다.
;; 스키마만 따로 검사하면 리더가 거부하는 경우를 놓친다.

;;; Code:

(require 'ert)
(require 'mrq-core)
(require 'mrq-test-helper)

(defconst mrq-schema-test--states '("todo" "done" "replied" "skipped")
  "`local.state' 의 enum.  `schema/review.schema.json'.")

(defconst mrq-schema-test--confidences '("exact" "fuzzy" "stale")
  "`location.confidence' 의 enum.")

(defconst mrq-schema-test--required
  '("schema_version" "project" "iid" "title" "web_url" "mr_state"
    "source_branch" "diff_refs" "me" "capabilities" "pulled_at" "threads")
  "최상위 필수 필드.")

(ert-deftest mrq-schema-every-sample-loads-through-the-real-reader ()
  (let ((samples (directory-files
                  (expand-file-name "review" mrq-test-data-dir) t "\\.json\\'")))
    (should samples)
    (dolist (sample samples)
      (let ((text (with-temp-buffer (insert-file-contents sample) (buffer-string))))
        (mrq-test-with-repo (root :review text)
          (let* ((dir (mrq-core-review-dir (expand-file-name "x.py" root)))
                 (review (mrq-core-review dir)))
            (should (cons sample (hash-table-p review)))
            (dolist (key mrq-schema-test--required)
              (should (cons (list sample key) (gethash key review))))
            (dolist (thread (gethash "threads" review))
              (let ((local (gethash "local" thread))
                    (location (gethash "location" thread)))
                (should (cons sample (gethash "id" thread)))
                (should (cons sample (hash-table-p (gethash "server" thread))))
                (should (member (gethash "state" local) mrq-schema-test--states))
                (when (hash-table-p location)
                  (should (member (gethash "confidence" location)
                                  mrq-schema-test--confidences))
                  (should (stringp (gethash "path" location))))))))))))

(provide 'mrq-schema-test)
;;; mrq-schema-test.el ends here
