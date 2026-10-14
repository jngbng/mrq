;;; mrq-smoke-test.el --- 하네스가 도는지 -*- lexical-binding: t -*-
;;; Commentary:
;; Task 2 에서 지운다.  이 파일의 목적은 `make test-emacs' 가 실제로 ERT 를
;; 돌리고 실패를 실패로 보고한다는 것을 한 번 보이는 것이다.
;;; Code:

(require 'mrq-smoke)

(ert-deftest mrq-smoke-harness-runs ()
  (should (equal (mrq-smoke-hello) "mrq")))

(provide 'mrq-smoke-test)
;;; mrq-smoke-test.el ends here
