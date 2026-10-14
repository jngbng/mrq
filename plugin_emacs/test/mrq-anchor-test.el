;;; mrq-anchor-test.el --- 적합성 테이블 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `testdata/conformance/anchor.json' 을 그대로 돌린다 (`repo-layout.md' §4.1).
;; 세 구현이 어긋나는 것을 막는 유일한 장치이므로, 케이스를 여기에 하드코딩하지
;; 말 것 — 테이블이 정본이고 계획 5 가 같은 파일을 읽는다.

;;; Code:

(require 'ert)
(require 'mrq-anchor)

(defconst mrq-anchor-test--table
  (expand-file-name "../../testdata/conformance/anchor.json"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "세 구현이 공유하는 적합성 테이블의 경로.")

(defun mrq-anchor-test--expand (case)
  "CASE 의 버퍼 서술을 1 행이 인덱스 0 인 문자열 벡터로 펼친다.

`buffer_repeat' 는 큰 버퍼를 json 에 펼치지 않으려는 것이고, `buffer_set' 은
그 버퍼의 `at' 번째 줄(1-indexed)을 **치환**한다 — 삽입이 아니므로 길이가
`count' 그대로이고 순서에 무관하다."
  (let ((plain (gethash "buffer" case))
        (repeat (gethash "buffer_repeat" case)))
    (if repeat
        (let ((lines (make-vector (gethash "count" repeat) (gethash "line" repeat))))
          (dolist (set (gethash "buffer_set" case) lines)
            (aset lines (1- (gethash "at" set)) (gethash "line" set))))
      (vconcat plain))))

(ert-deftest mrq-anchor-conformance ()
  "`testdata/conformance/anchor.json' 의 모든 케이스."
  (let ((cases (with-temp-buffer
                 (insert-file-contents mrq-anchor-test--table)
                 (goto-char (point-min))
                 (json-parse-buffer :array-type 'list))))
    (should (= (length cases) 17))
    (dolist (case cases)
      (let* ((name (gethash "name" case))
             (lines (mrq-anchor-test--expand case))
             (got (mrq-anchor-correct lines
                                      (gethash "anchor_line" case)
                                      (gethash "location_line" case)))
             (want (gethash "expect" case)))
        ;; 실패 메시지에 케이스 이름이 나오도록 cons 로 묶어 비교한다.
        (should (equal (cons name got) (cons name want)))))))

(provide 'mrq-anchor-test)
;;; mrq-anchor-test.el ends here
