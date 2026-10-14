;;; mrq-mode.el --- review.md 목록 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.2.  `review.md' 의 메이저 모드다.
;;
;; 이 파일은 `review.md' 에서 **점을 옮기기 위한 검색**만 한다 — 상태나 답글을
;; 추출하지 않는다.  그 값을 읽는 경로는 `review.json' 하나이고 (`mrq-core'),
;; md -> json 변환은 `mrq sync' 하나다 (`editor.md' §1-1).
;;
;; `C-c C-t' 의 체크박스 순환도 **문자 치환**일 뿐이다.  의미는 `sync' 가 준다.

;;; Code:

(require 'cl-lib)
(require 'compile)
(require 'markdown-mode)
(require 'subr-x)
(require 'mrq-anchor)
(require 'mrq-cli)
(require 'mrq-core)

;; 충돌 UI 와 flymake 는 필요할 때 끌어온다 — 목록 버퍼를 여는 것만으로
;; 그 둘을 로드할 이유가 없다.
(declare-function mrq-conflict-show "mrq-conflict")
(declare-function mrq-flymake-thread-at-point "mrq-flymake")
(defvar mrq-conflict-buffer-name)

(defconst mrq-mode-header-re "^## \\[.\\] \\(.+?\\):\\([0-9]+\\)"
  "위치가 있는 스레드 헤더.  `review-md.md' §3.

`(general)' 헤더는 **의도적으로** 매치되지 않는다 — 위치를 못 찾은 것이
아니라 위치가 없는 코멘트이고, 가짜 위치로 점프시키면 안 된다.")

(defconst mrq-mode-anchor-re
  "^<!-- mrq:\\([0-9a-f]\\{8,\\}\\)\\(?: v:[0-9a-f]\\{6\\}\\)? -->$"
  "스레드 블록의 경계.  `review-md.md' §2 — 앵커는 헤더 **위**에 있다.")

(defconst mrq-mode--state-cycle '(?\s ?x ?~ ?-)
  "`C-c C-t' 의 순환 순서.  `review-md.md' §3 의 상태 문자.")

(defvar mrq-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "RET") #'mrq-mode-visit)
    (define-key map (kbd "C-c C-t") #'mrq-mode-toggle-state)
    (define-key map (kbd "C-c C-s") #'mrq-mode-sync)
    (define-key map (kbd "C-c C-p") #'mrq-mode-push)
    (define-key map (kbd "g") #'mrq-mode-pull)
    (define-key map (kbd "r") #'mrq-mode-reanchor)
    map)
  "`mrq-mode' 의 키맵.")

(add-to-list 'compilation-error-regexp-alist-alist
             (list 'mrq mrq-mode-header-re 1 2))

;;;###autoload
(define-derived-mode mrq-mode markdown-mode "MRQ"
  "`review.md' 를 다루는 메이저 모드.

`markdown-mode' 에서 파생하는 이유는 답글에 표·코드펜스·수평선이 평범하게
들어오기 때문이다 (`review-md.md' §1)."
  (setq-local compilation-error-regexp-alist '(mrq))
  (setq-local next-error-function #'mrq-mode-next-error)
  (add-hook 'after-save-hook #'mrq-mode--after-save nil t))

;;;###autoload
(add-to-list 'auto-mode-alist '("/\\.mrq/[^/]+/review\\.md\\'" . mrq-mode))

(defun mrq-mode--repo-root ()
  "`review.md' 가 속한 리포 루트.

`default-directory' 를 쓰면 안 된다 — 헤더의 경로는 **리포 상대**이고 이
버퍼는 `.mrq/<iid>/' 에 있다."
  (or (mrq-core-root (buffer-file-name))
      (user-error "리포 루트를 찾을 수 없습니다 (.mrq/current 가 없습니다)")))

(defun mrq-mode--header-at-point ()
  "point 가 속한 블록의 헤더에서 (경로 . 줄).  위치 헤더가 아니면 nil."
  (save-excursion
    (beginning-of-line)
    (unless (looking-at mrq-mode-header-re)
      (when (re-search-backward mrq-mode-anchor-re nil t)
        (forward-line 1)))
    (when (looking-at mrq-mode-header-re)
      (cons (match-string-no-properties 1)
            (string-to-number (match-string-no-properties 2))))))

(defun mrq-mode-visit ()
  "point 의 스레드가 가리키는 소스 위치로 이동한다."
  (interactive)
  (let ((target (mrq-mode--header-at-point)))
    (unless target
      (user-error "여기에는 위치가 있는 스레드 헤더가 없습니다"))
    (let ((path (expand-file-name (car target) (mrq-mode--repo-root))))
      (unless (file-exists-p path)
        (user-error "%s 가 없습니다" (car target)))
      (find-file path)
      (goto-char (point-min))
      (forward-line (1- (cdr target))))))

(defun mrq-mode-next-error (n reset)
  "`next-error-function'.  N 개 앞/뒤로, RESET 이면 처음부터.

`(general)' 헤더는 `mrq-mode-header-re' 가 잡지 않으므로 자연히 건너뛴다."
  (when reset (goto-char (point-min)))
  (let ((forward (>= n 0)))
    (dotimes (_ (max 1 (abs n)))
      (if forward
          (progn
            (end-of-line)
            (unless (re-search-forward mrq-mode-header-re nil t)
              (user-error "다음 코멘트가 없습니다")))
        (beginning-of-line)
        (unless (re-search-backward mrq-mode-header-re nil t)
          (user-error "이전 코멘트가 없습니다")))
      (beginning-of-line)))
  (mrq-mode-visit))

(defun mrq-mode-toggle-state ()
  "point 가 속한 블록의 체크박스를 순환시킨다.

`[ ]' -> `[x]' -> `[~]' -> `[-]' -> `[ ]'.  **문자만 바꾼다** — 이 함수는
상태의 의미를 해석하지 않고, 반영은 저장 시 `mrq sync' 가 한다."
  (interactive)
  (save-excursion
    (beginning-of-line)
    (unless (looking-at "^## \\[.\\]")
      (if (re-search-backward mrq-mode-anchor-re nil t)
          (forward-line 1)
        (user-error "스레드 블록 안이 아닙니다")))
    (unless (looking-at "^## \\[\\(.\\)\\]")
      (user-error "스레드 헤더를 찾을 수 없습니다"))
    (let* ((current (string-to-char (match-string 1)))
           (rest (cdr (memq current mrq-mode--state-cycle)))
           (next (or (car rest) (car mrq-mode--state-cycle))))
      (replace-match (char-to-string next) t t nil 1))))


;;; CLI 호출과 보고

(defconst mrq-mode-buffer-name "*mrq*"
  "로그와 점프 가능한 메시지가 모이는 버퍼.")

(defun mrq-mode--after-save ()
  "`review.md' 를 저장하면 `mrq sync' 를 돌린다 (`editor.md' §3.3).

소스 파일 저장에는 아무것도 하지 않는다 — 이 훅은 `mrq-mode' 버퍼에만
걸리므로 그 구분이 자동으로 된다."
  (mrq-mode-sync))

(defun mrq-mode-sync ()
  "`mrq sync --json' 을 돌리고 결과에 따라 버퍼를 되읽는다."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("sync" "--json") nil (mrq-mode--repo-root))
                    :revert t))

(defun mrq-mode-reanchor ()
  "`mrq reanchor --json'.  네트워크를 쓰지 않는다 (`cli.md' §6)."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("reanchor" "--json") nil (mrq-mode--repo-root))
                    :revert t))

(defun mrq-mode-pull ()
  "`mrq pull' 후 버퍼를 되읽는다."
  (interactive)
  (mrq-mode--report (mrq-cli-run '("pull") nil (mrq-mode--repo-root))
                    :revert t))

(defun mrq-mode-push ()
  "`mrq status' 요약을 보여주고 확인을 받은 뒤 `mrq push'.

되돌릴 수 없는 작업이므로 확인을 받는다 — CLI 의 `prompt.confirm' 과 같은
규율이다."
  (interactive)
  (let* ((root (mrq-mode--repo-root))
         (status (mrq-cli-run '("status" "--json") nil root)))
    (unless (= (plist-get status :code) 0)
      (mrq-mode--report status)
      (user-error "status 가 실패했습니다"))
    (when (yes-or-no-p (concat (string-trim (plist-get status :stderr))
                               "\npush 할까요? "))
      (mrq-mode--report (mrq-cli-run '("push" "--json") nil root) :revert t))))

(cl-defun mrq-mode--report (result &key revert)
  "RESULT 의 종료 코드에 따라 보고하고, 성공이면 버퍼를 되읽는다.

exit 2(파싱 에러)와 exit 3(충돌)에는 **되읽지 않는다** — CLI 가 아무것도
쓰지 않았고, exit 2 는 고칠 내용이 지금 버퍼에 있다."
  (let ((code (plist-get result :code))
        (payload (plist-get result :json)))
    (cond
     ((= code 0)
      (mrq-mode--log-messages payload "warnings")
      (when revert (mrq-mode--revert-keeping-thread))
      (message "%s" (mrq-mode--summary result payload)))
     ((= code 2)
      (mrq-mode--log-messages payload "errors")
      (unless payload (mrq-mode--log (string-trim (plist-get result :stderr))))
      (message "파싱 에러 — %s 에서 C-x `" mrq-mode-buffer-name))
     ((= code 3) (mrq-mode--on-conflict payload))
     (t
      (mrq-mode--log (string-trim (plist-get result :stderr)))
      (user-error "mrq: %s"
                  (car (split-string (string-trim (plist-get result :stderr))
                                     "\n")))))))

(defun mrq-mode--on-conflict (payload)
  "exit 3 — 충돌 버퍼를 띄운다.

버퍼는 되읽지 않는다 (CLI 가 아무것도 쓰지 않았다)."
  (require 'mrq-conflict)
  (mrq-conflict-show payload (mrq-core-review-dir (buffer-file-name)))
  (message "충돌 %d건 — %s 에서 고르세요"
           (length (gethash "conflicts" payload))
           mrq-conflict-buffer-name))

(defun mrq-mode--summary (result payload)
  "에코 영역 한 줄."
  (if (null payload)
      (or (car (split-string (string-trim (plist-get result :stdout)) "\n")) "완료")
    (let ((applied (gethash "applied" payload))
          (anchors (gethash "anchors" payload))
          (warnings (gethash "warnings" payload)))
      (concat (when applied (format "applied %d" (length applied)))
              (when anchors
                (format " · exact %s fuzzy %s stale %s"
                        (gethash "exact" anchors) (gethash "fuzzy" anchors)
                        (gethash "stale" anchors)))
              (when (and warnings (> (length warnings) 0))
                (format " · 경고 %d건 (%s)" (length warnings) mrq-mode-buffer-name))))))

(defun mrq-mode--log-messages (payload key)
  "PAYLOAD 의 KEY (\"warnings\" 또는 \"errors\") 를 `*mrq*' 에 넣는다.

`line' 이 `null' 인 경고에 **위치를 만들어내지 않는다** (`cli.md' §5
MUST NOT).  `review.md:0' 도 1 행도 쓰지 않고 접두사 없는 평문으로 둔다 —
가짜 위치가 위치 신뢰를 잃는 가장 빠른 길이다 (`data-model.md' §4.9)."
  (dolist (item (and payload (gethash key payload)))
    (mrq-mode--log (mrq-mode--format-message item))))

(defun mrq-mode--format-message (item)
  "`{line, message}' 를 `review.md:<line>: <message>' 또는 평문으로."
  (let ((line (gethash "line" item))
        (text (gethash "message" item)))
    (if (numberp line)
        (format "review.md:%d: %s" line text)
      text)))

(defun mrq-mode--log (text)
  "TEXT 를 `*mrq*' 에 넣는다.  그 버퍼는 `compilation-mode' 다.

`default-directory' 를 리뷰 디렉터리로 두면 `review.md:142:' 가 그대로
점프 가능해진다."
  (let ((dir (mrq-core-review-dir (buffer-file-name))))
    (with-current-buffer (get-buffer-create mrq-mode-buffer-name)
      (let ((inhibit-read-only t))
        (unless (derived-mode-p 'compilation-mode)
          (compilation-mode)
          (setq-local compilation-error-regexp-alist '(mrq)))
        (when dir (setq-local default-directory dir))
        (goto-char (point-max))
        (insert text "\n")))))

(defun mrq-mode--thread-at-point ()
  "point 위의 가장 가까운 앵커의 (thread-id . 블록 안 오프셋).  없으면 nil."
  (save-excursion
    (let ((here (line-number-at-pos)))
      (beginning-of-line)
      (when (or (looking-at mrq-mode-anchor-re)
                (re-search-backward mrq-mode-anchor-re nil t))
        (cons (match-string-no-properties 1)
              (- here (line-number-at-pos)))))))

(defun mrq-mode--revert-keeping-thread ()
  "버퍼를 되읽고 point 를 **스레드 id 기준**으로 복원한다.

줄 번호로 복원하면 재렌더로 앞 블록의 줄 수가 바뀔 때마다 커서가 흘러간다 —
답글을 쓸 때마다 일어난다."
  (let ((anchor (mrq-mode--thread-at-point)))
    (revert-buffer t t t)
    (when anchor
      (goto-char (point-min))
      (if (re-search-forward (format "^<!-- mrq:%s " (regexp-quote (car anchor))) nil t)
          (progn (beginning-of-line) (forward-line (cdr anchor)))
        (goto-char (point-min))))))


;;;###autoload
(defun mrq-reply-at-point ()
  "point 의 진단이 가리키는 스레드의 `### reply' 로 점프한다.

`review.md' 에서 **점을 옮기기 위한 검색**은 파싱이 아니다 (`editor.md' §1) —
상태나 답글을 추출하지 않고, 틀려야 커서가 엉뚱한 데 가며 사용자가 즉시 본다.
md 에서 값을 읽는 경로는 없고, md -> json 변환은 `mrq sync' 하나다.

소스 <-> 목록 왕복이 이것으로 닫힌다."
  (interactive)
  (require 'mrq-flymake)
  (let ((id (mrq-flymake-thread-at-point)))
    (unless id
      (user-error "여기에 MR 코멘트가 없습니다"))
    (let* ((dir (mrq-core-review-dir (buffer-file-name)))
           (md (and dir (expand-file-name "review.md" dir))))
      (unless (and md (file-exists-p md))
        (user-error "review.md 가 없습니다 — `mrq pull --render' 로 복원하세요"))
      (pop-to-buffer (find-file-noselect md))
      (goto-char (point-min))
      (unless (re-search-forward (format "^<!-- mrq:%s " (regexp-quote id)) nil t)
        (user-error "%s 의 블록이 review.md 에 없습니다" id))
      (if (re-search-forward "^### reply$" nil t)
          (progn (forward-line 1)
                 (when (looking-at "^$") (forward-line 1)))
        (beginning-of-line)))))

(provide 'mrq-mode)
;;; mrq-mode.el ends here
