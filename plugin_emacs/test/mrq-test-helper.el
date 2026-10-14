;;; mrq-test-helper.el --- 테스트 픽스처 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `docs/spec/testing.md' §2 의 가짜 `glab' 수법을 그대로 가져온다 — 모킹이
;; 아니라 진짜 프로세스와 진짜 파일을 쓴다.  모킹한 `call-process' 는 stdout 과
;; stderr 의 분리나 종료 코드를 틀리게 흉내 내기 쉽고, 그 둘이 정확히
;; `mrq-cli.el' 이 책임지는 것이다.

;;; Code:

(require 'ert)
(require 'mrq-core)

(defun mrq-test-wait-for (predicate &optional seconds)
  "PREDICATE 가 non-nil 이 될 때까지 최대 SECONDS(기본 3) 기다린다.

`file-notify' 와 flymake 는 둘 다 비동기라 여러 테스트 파일이 이것을 쓴다.
테스트 파일 사이의 로드 순서에 기대지 않도록 헬퍼에 둔다.

**batch 에서는 `read-event' 만 inotify 이벤트를 흘려보낸다.**  `sit-for',
`sleep-for', `accept-process-output' 셋은 `emacs -Q -batch' 에서 이벤트를
전혀 배달하지 않는다(실측).  `read-event' 는 대화형에서 키 입력을 훔치므로
`noninteractive' 일 때만 쓴다."
  (let ((deadline (+ (float-time) (or seconds 3))))
    (while (and (not (funcall predicate)) (< (float-time) deadline))
      ;; 프로세스 기반 백엔드(예: `python-flymake')와 inotify 를 **둘 다**
      ;; 흘려보내야 한다 — `accept-process-output' 은 프로세스만,
      ;; `read-event' 는 파일 알림만 배달한다.
      (accept-process-output nil 0.01)
      (if noninteractive
          (read-event nil nil 0.04)
        (sit-for 0.04)))
    (funcall predicate)))

(defconst mrq-test-data-dir
  (expand-file-name "../../testdata/"
                    (file-name-directory (or load-file-name buffer-file-name)))
  "세 구현이 공유하는 테스트 데이터 디렉터리.")

(defun mrq-test-sample-review ()
  "`testdata/review/rendered.json' 의 내용."
  (with-temp-buffer
    (insert-file-contents (expand-file-name "review/rendered.json" mrq-test-data-dir))
    (buffer-string)))

(defmacro mrq-test-with-repo (spec &rest body)
  "임시 리포를 만들고 SPEC 의 첫 심볼에 루트를 바인딩한 채 BODY 를 실행한다.

SPEC 은 (ROOT &key REVIEW IID FILES SYMLINK) 다.
REVIEW 는 `review.json' 의 문자열 내용 (기본 `mrq-test-sample-review').
IID 는 정수 (기본 1234).
FILES 는 (상대경로 . 내용) 의 alist.
SYMLINK 가 nil 이면 `current' 를 심링크가 아니라 iid 를 담은 일반 파일로 쓴다
\(`data-model.md' §1 이 허용하는 fallback)."
  (declare (indent 1) (debug t))
  (let* ((root (car spec))
         (opts (cdr spec))
         (symlink (if (plist-member opts :symlink) (plist-get opts :symlink) t)))
    `(let* ((,root (file-truename (make-temp-file "mrq-test-" t)))
            (iid (or ,(plist-get opts :iid) 1234))
            (review-dir (expand-file-name (format ".mrq/%d" iid) ,root)))
       (unwind-protect
           (progn
             (make-directory review-dir t)
             (write-region (or ,(plist-get opts :review) (mrq-test-sample-review))
                           nil (expand-file-name "review.json" review-dir) nil 'quiet)
             (if ,symlink
                 (make-symbolic-link (format "%d" iid)
                                     (expand-file-name ".mrq/current" ,root))
               (write-region (format "%d\n" iid) nil
                             (expand-file-name ".mrq/current" ,root) nil 'quiet))
             (dolist (entry ,(plist-get opts :files))
               (let ((path (expand-file-name (car entry) ,root)))
                 (make-directory (file-name-directory path) t)
                 (write-region (cdr entry) nil path nil 'quiet)))
             ,@body)
         (mrq-test-kill-buffers-under ,root)
         (mrq-core-forget-all)
         (delete-directory ,root t)))))

(defun mrq-test-kill-buffers-under (root)
  "ROOT 아래 파일을 방문 중인 버퍼를 전부 죽인다.

남겨 두면 다음 테스트가 같은 경로의 낡은 버퍼를 집는다 — 임시 디렉터리
이름이 매번 달라도 `find-file-noselect' 가 만든 버퍼는 세션에 남는다."
  (dolist (buffer (buffer-list))
    (let ((path (buffer-file-name buffer)))
      (when (and path (string-prefix-p (file-name-as-directory root) path))
        (with-current-buffer buffer (set-buffer-modified-p nil))
        (kill-buffer buffer)))))

(defun mrq-test-write-review (root iid text)
  "ROOT/.mrq/IID/review.json 을 TEXT 로 **원자적으로 교체**한다.

CLI 가 `os.replace' 를 쓰므로(`store.py:179') 테스트도 같은 모양이어야 한다 —
제자리 덮어쓰기로 테스트하면 inode 가 안 바뀌어 파일 watch 의 결함을 놓친다."
  (let* ((dir (expand-file-name (format ".mrq/%d" iid) root))
         (final (expand-file-name "review.json" dir))
         (tmp (expand-file-name ".review.json.tmp" dir)))
    (write-region text nil tmp nil 'quiet)
    (rename-file tmp final t)))

(defun mrq-test-fake-cli (root &rest opts)
  "ROOT 에 가짜 `mrq' 실행 파일을 깔고 그 경로를 돌려준다.

모킹이 아니라 진짜 프로세스다 (`testing.md' §2).  호출될 때마다 argv 를
`calls.txt' 에 한 줄씩, stdin 을 `stdin.txt' 에 덮어쓰고, OPTS 가 지정한
stdout/stderr/종료 코드를 낸다.

`:writes' 가 (경로 . 내용) 이면 그 파일을 덮어쓴다.  진짜 `mrq sync' 가
`review.md' 를 재렌더하는 것을 그대로 흉내 내기 위한 것이다 — Emacs 쪽
`after-save-hook' 으로 흉내 내면 훅 순서와 modtime 처리가 끼어들어 실제와
다른 것을 시험하게 된다."
  (let* ((path (expand-file-name "fake-mrq" root))
         (code (or (plist-get opts :code) 0))
         (stdout (or (plist-get opts :stdout) ""))
         (stderr (or (plist-get opts :stderr) ""))
         (writes (plist-get opts :writes))
         (payload (and writes (expand-file-name "fake-write-payload" root))))
    (when writes
      (write-region (cdr writes) nil payload nil 'quiet))
    (write-region
     (concat "#!/bin/sh\n"
             "printf '%s\\n' \"$*\" >> " (shell-quote-argument
                                          (expand-file-name "calls.txt" root)) "\n"
             "pwd >> " (shell-quote-argument
                        (expand-file-name "cwd.txt" root)) "\n"
             "cat > " (shell-quote-argument
                       (expand-file-name "stdin.txt" root)) "\n"
             (if writes
                 (concat "cp " (shell-quote-argument payload) " "
                         (shell-quote-argument (car writes)) "\n")
               "")
             "printf '%s' " (shell-quote-argument stdout) "\n"
             "printf '%s' " (shell-quote-argument stderr) " >&2\n"
             "exit " (number-to-string code) "\n")
     nil path nil 'quiet)
    (set-file-modes path #o755)
    path))

(defun mrq-test-cli-calls (root)
  "가짜 `mrq' 가 받은 호출들.  각 원소는 인자 문자열 하나."
  (let ((log (expand-file-name "calls.txt" root)))
    (when (file-exists-p log)
      (split-string (with-temp-buffer
                      (insert-file-contents log)
                      (buffer-string))
                    "\n" t))))

(defun mrq-test-cli-cwds (root)
  "가짜 `mrq' 가 돈 작업 디렉터리들.

CLI 는 cwd 에서 리포를 찾으므로(`store.py') 이것이 틀리면 엉뚱한 리포를 본다."
  (let ((log (expand-file-name "cwd.txt" root)))
    (when (file-exists-p log)
      (split-string (with-temp-buffer (insert-file-contents log) (buffer-string))
                    "\n" t))))

(defun mrq-test-cli-stdin (root)
  "가짜 `mrq' 가 마지막으로 받은 stdin."
  (let ((path (expand-file-name "stdin.txt" root)))
    (when (file-exists-p path)
      (with-temp-buffer (insert-file-contents path) (buffer-string)))))

(provide 'mrq-test-helper)
;;; mrq-test-helper.el ends here
