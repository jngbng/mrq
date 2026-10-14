;;; mrq-cli.el --- mrq 프로세스 호출 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `mrq' 를 띄우는 **유일한** 자리다.  `mrq-boundary-test.el' 이 그것을 고정한다.
;;
;; stdout 과 stderr 를 반드시 분리한다 — `cli.md' §2 가 "stdout 은 순수 JSON,
;; 경고·에러는 stderr" 를 MUST 로 두는데, 섞으면 경고 한 줄에 페이로드 파싱이
;; 깨진다.  `call-process' 의 (버퍼 stderr-파일) 형태가 그것을 해 준다.
;;
;; 동기 실행이다.  비동기가 필요한 유일한 후보는 `push'(실측 16 초)인데
;; `C-c C-p' 는 확인을 받고 돌리는 명시적 조작이라 블로킹이 맞다.

;;; Code:

(require 'mrq-core)

(defun mrq-cli-run (args &optional stdin dir)
  "`mrq' 를 ARGS 로 실행한다.  STDIN 이 있으면 표준 입력으로 넘긴다.

DIR 은 작업 디렉터리 (기본 `default-directory').  결과는 plist —
:code 종료 코드, :stdout 문자열, :stderr 문자열, :json 파싱된 stdout 또는 nil.

본문을 인자로 넘기지 않는 것이 규약이다 — `mrq reply -F -' 가 그것을 위해 있다.

실행 자체가 실패해도(실행 파일 없음 등) 에러를 올리지 않는다.  호출자가
저장 훅과 flymake 경로라 예외가 편집을 막는다."
  (let* ((default-directory (file-name-as-directory (or dir default-directory)))
         (stderr-file (make-temp-file "mrq-stderr-"))
         (stdin-file (and stdin (make-temp-file "mrq-stdin-")))
         (stdout "")
         (code nil))
    (unwind-protect
        (with-temp-buffer
          (when stdin-file
            (write-region stdin nil stdin-file nil 'quiet))
          (setq code (condition-case err
                         (apply #'call-process mrq-executable stdin-file
                                (list (current-buffer) stderr-file) nil args)
                       (error (mrq-core-log (error-message-string err))
                              (error-message-string err))))
          (setq stdout (buffer-string)))
      (when stdin-file (delete-file stdin-file)))
    (let ((stderr (with-temp-buffer
                    (insert-file-contents stderr-file)
                    (prog1 (buffer-string) (delete-file stderr-file)))))
      (list :code (if (numberp code) code 1)
            :stdout stdout
            :stderr (if (stringp code) (concat stderr code "\n") stderr)
            :json (mrq-cli--parse stdout)))))

(defun mrq-cli--parse (text)
  "TEXT 가 JSON 객체면 파싱해 돌려준다.  아니면 nil.

`pull'/`open'/`doctor' 처럼 `--json' 이 없는 명령은 평문을 내므로 실패가
정상이다.  여기서 에러를 내면 그 명령들이 전부 깨진다."
  (and (string-match-p "\\`[ \t\n]*{" text)
       (condition-case nil
           (with-temp-buffer
             (insert text)
             (goto-char (point-min))
             (json-parse-buffer :array-type 'list))
         (error nil))))

(provide 'mrq-cli)
;;; mrq-cli.el ends here
