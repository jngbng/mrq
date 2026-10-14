;;; mrq-core.el --- 리뷰 상태 접근 계층 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `review.json' 을 읽는 **유일한** 창구다.  다른 모듈에 `json-parse' 가 없는
;; 것이 `editor.md' §1-1 (md 를 파싱하지 않는다)을, 이 파일에 쓰기 함수가 없는
;; 것이 §1-2 (json 을 직접 쓰지 않는다)를 코드 모양으로 보장한다.
;; `mrq-boundary-test.el' 이 그 둘을 테스트로 고정한다.
;;
;; `git' 을 부르지 않는다 (§1-4).  리포 루트는 `.mrq/current' 를 위로 찾아
;; 얻는다 (§2) — 디렉터리 탐색이지 git 호출이 아니고, 리포가 이동해도 동작한다.

;;; Code:

(require 'cl-lib)
(require 'filenotify)
(require 'subr-x)

(defgroup mrq nil
  "GitLab MR 리뷰 코멘트를 버퍼에서 다룬다."
  :group 'tools
  :prefix "mrq-")

(defcustom mrq-executable "mrq"
  "`mrq' CLI 의 경로.  `repo-layout.md' §5."
  :type 'string
  :group 'mrq)

(defcustom mrq-show-handled nil
  "non-nil 이면 처리한 스레드와 서버에서 resolve 된 스레드도 진단으로 띄운다.

`mrq list --all' 과 같은 집합이 된다.  기본값이 nil 인 이유는 `editor.md'
§3.1 — 120 초 예산에서 보고 싶은 것은 \"남은 것\" 이다."
  :type 'boolean
  :group 'mrq)

(defconst mrq-core-schema-version 1
  "이 플러그인이 읽을 수 있는 `review.json' 의 `schema_version'.")

(defvar mrq-core-refresh-functions nil
  "`mrq-core-refresh' 가 부르는 훅.  인자는 리뷰 디렉터리 하나.

`mrq-flymake.el' 이 여기에 붙어 열린 버퍼의 진단을 다시 돌린다.  `mrq-core'
가 flymake 를 직접 부르지 않는 이유는 의존을 한쪽으로만 흘리기 위해서다.")

(defvar mrq-core--cache (make-hash-table :test 'equal)
  "리뷰 디렉터리 -> 파싱된 `review.json'.  무효화는 watch 알림으로만 한다.")

(defvar mrq-core--watches (make-hash-table :test 'equal)
  "리뷰 디렉터리 -> `file-notify' 디스크립터.")

(defvar mrq-core--warned (make-hash-table :test 'equal)
  "경고를 이미 낸 (디렉터리 . 키) 쌍.")

(defvar-local mrq-core--root nil
  "이 버퍼가 속한 리포 루트.  `current' 와 달리 세션 중에 바뀌지 않는다.")

(defun mrq-core-root (&optional file)
  "FILE(기본 `buffer-file-name')이 속한 리포 루트.  없으면 nil.

성공만 버퍼 로컬에 기억한다.  실패를 기억하면 `mrq pull' 전에 열어 둔 버퍼가
영원히 죽는다 — 탐색은 `file-exists-p' 몇 번이라 매번 해도 싸다."
  (or mrq-core--root
      (let* ((path (or file buffer-file-name))
             (found (and path
                         (locate-dominating-file
                          path
                          (lambda (dir)
                            (file-exists-p (expand-file-name ".mrq/current" dir)))))))
        (when found
          (setq found (expand-file-name found))
          (when (equal path (buffer-file-name))
            (setq mrq-core--root found))
          found))))

(defun mrq-core-review-dir (&optional file)
  "FILE 이 속한 리뷰 디렉터리.  없으면 nil.

`current' 는 **접근할 때마다 다시 푼다** — `mrq pull --mr 9' 가 심링크를 갈아
끼우면 따라가야 한다.  디렉터리를 캐시하면 옛 MR 의 코멘트를 계속 보여준다.

**심링크를 끝까지 푼 실제 경로(`.mrq/<iid>/')를 돌려준다**(MUST).
`.mrq/current/' 를 그대로 돌려주면 두 가지가 깨진다 — 캐시 키가 MR 마다
달라지지 않아 `current' 가 다른 MR 을 가리켜도 옛 파싱 결과가 살아남고,
`file-notify' 가 심링크 경로에 걸려 알림이 오지 않는다(실측)."
  (let ((root (mrq-core-root file)))
    (when root
      (let ((current (expand-file-name ".mrq/current" root)))
        (cond
         ((file-directory-p current)
          (file-name-as-directory (file-truename current)))
         ((file-exists-p current)
          (let ((iid (string-trim (with-temp-buffer
                                    (insert-file-contents current)
                                    (buffer-string)))))
            (unless (string-empty-p iid)
              (let ((dir (expand-file-name (concat ".mrq/" iid) root)))
                (file-name-as-directory (file-truename dir)))))))))))

(defun mrq-core-review (dir)
  "DIR 의 `review.json' 을 파싱해 돌려준다.  모르는 스키마면 nil.

읽을 때마다 watch 를 보장한다 — 등록이 여기 있는 이유는 `review.json' 이 아직
없을 수도 있기 때문이다(첫 `pull' 전)."
  (when dir
    (mrq-core--ensure-watch dir)
    (let ((hit (gethash dir mrq-core--cache 'miss)))
      (if (eq hit 'miss)
          (puthash dir (mrq-core--load dir) mrq-core--cache)
        hit))))

(defun mrq-core--load (dir)
  "DIR/review.json 을 읽는다.  실패하거나 스키마를 모르면 nil.

에러를 올리지 않는다 — 호출자가 flymake 백엔드라 예외가 편집을 막는다."
  (let ((path (expand-file-name "review.json" dir)))
    (when (file-readable-p path)
      (let ((parsed (condition-case err
                        (with-temp-buffer
                          (insert-file-contents path)
                          (goto-char (point-min))
                          (json-parse-buffer :array-type 'list))
                      (error
                       (mrq-core--warn-once
                        dir 'unreadable
                        (format "mrq: %s 를 읽을 수 없습니다 — %s"
                                path (error-message-string err)))
                       nil))))
        (when parsed
          (let ((version (gethash "schema_version" parsed)))
            (if (equal version mrq-core-schema-version)
                parsed
              (mrq-core--warn-once
               dir version
               (format (concat "mrq: %s 의 schema_version 이 %s 입니다 "
                               "(이 mrq.el 은 %d). 동작을 거부합니다 — "
                               "mrq.el 또는 mrq CLI 를 업데이트하세요.")
                       path version mrq-core-schema-version))
              nil)))))))

(defun mrq-core--warn-once (dir key text)
  "DIR 과 KEY 의 쌍마다 TEXT 를 한 번만 낸다.

flymake 가 편집 중 반복 호출되므로 매번 내면 미니버퍼를 못 쓴다."
  (let ((seen (cons dir key)))
    (unless (gethash seen mrq-core--warned)
      (puthash seen t mrq-core--warned)
      (message "%s" text)
      (mrq-core-log text))))

(defun mrq-core-log (text)
  "TEXT 를 `*mrq*' 버퍼에 남긴다."
  (with-current-buffer (get-buffer-create "*mrq*")
    (let ((inhibit-read-only t))
      (goto-char (point-max))
      (insert text "\n"))))

(defun mrq-core-threads-for (file)
  "FILE 의 리포 상대 경로를 `location.path' 로 가진 스레드들."
  (let* ((root (mrq-core-root file))
         (review (and root (mrq-core-review (mrq-core-review-dir file)))))
    (when review
      (let ((relative (file-relative-name (expand-file-name file) root))
            (out nil))
        (dolist (thread (gethash "threads" review) (nreverse out))
          (let ((location (gethash "location" thread)))
            (when (and (hash-table-p location)
                       (equal (gethash "path" location) relative))
              (push thread out))))))))

(defun mrq-core--ensure-watch (dir)
  "DIR 에 `file-notify' watch 를 보장한다.

파일이 아니라 **디렉터리**에 건다.  CLI 가 temp 파일 + `os.replace' 로
`review.json' 을 쓰므로(`store.py:179') inode 가 바뀌는데, 원시 inotify 에서는
파일에 건 watch 가 그 교체 뒤 끊긴 inode 에 남아 조용히 죽는다.

**Emacs 에서는 둘이 동등하다** — `file-notify-add-watch' 는 FILE 을 받아도
그 부모 디렉터리를 감시하고 이름으로 거른다.  rename 교체 3 회를 모두 받고,
아직 없는 파일에 걸어도 에러가 나지 않는 것을 실측했다.  그래도 디렉터리에
명시적으로 거는 이유는 동작이 그 구현 세부에 기대지 않게 하려는 것이고,
`plugin_vscode' 의 `FileSystemWatcher' 는 같은 보장을 준다고 가정할 수 없어
계획 5 가 거기서 따로 확인해야 하기 때문이다.

해제하지 않는다 — 상한이 \"이 세션에서 건드린 MR 수\" 라 누수가 아니고,
버퍼 단위로 걸고 풀면 `kill-buffer' 경로가 전부 샌다."
  (unless (gethash dir mrq-core--watches)
    (when (file-directory-p dir)
      (puthash dir
               (file-notify-add-watch
                dir '(change)
                (lambda (event) (mrq-core--on-change dir event)))
               mrq-core--watches))))

(defun mrq-core--on-change (dir event)
  "DIR 의 EVENT 가 `review.json' 에 대한 것이면 캐시를 버리고 진단을 갱신한다."
  (let ((files (cl-remove-if-not #'stringp (cddr event))))
    (when (cl-some (lambda (f) (equal (file-name-nondirectory f) "review.json"))
                   files)
      (mrq-core-refresh dir))))

(defun mrq-core-refresh (dir)
  "DIR 의 캐시를 버리고 `mrq-core-refresh-functions' 를 부른다."
  (remhash dir mrq-core--cache)
  (clrhash mrq-core--warned)
  (run-hook-with-args 'mrq-core-refresh-functions dir))

(defun mrq-core-forget-all ()
  "캐시와 watch 를 전부 버린다.  테스트 정리용."
  (clrhash mrq-core--cache)
  (clrhash mrq-core--warned)
  (maphash (lambda (_ descriptor) (file-notify-rm-watch descriptor))
           mrq-core--watches)
  (clrhash mrq-core--watches))

(provide 'mrq-core)
;;; mrq-core.el ends here
