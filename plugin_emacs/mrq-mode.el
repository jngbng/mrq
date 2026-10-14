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
  "체크박스 순환 순서.  `review-md.md' §3 의 상태 문자.")

(defvar mrq-mode-command-map (make-sparse-keymap)
  "`review.md' 에서 `C-c m' 뒤에 오는 키들.")

(defvar mrq-mode-map (make-sparse-keymap)
  "`mrq-mode' 의 키맵.

**평문 키도 `C-c' + 컨트롤 문자도 쓰지 않는다.**  이 버퍼는 `markdown-mode'
파생의 편집면이고, 그 공간은 부모가 이미 쓰고 있다 — 스타일 접두사(코드펜스·
표·굵게)와 제목 접두사가 특히 그렇다.
답글에 표와 코드펜스가 평범하게 들어온다는 것이 `review-md.md' §1 의 전제다.

그래서 소스 버퍼 쪽과 같은 `C-c m' 접두사를 쓴다 — `markdown-mode' 에서
비어 있고, 외울 접두사가 하나가 된다.")

;; 내용을 최상위에서 채우는 이유는 `mrq.el' 의 같은 자리와 같다 — `defvar' 가
;; 재평가에서 초기화 폼을 건너뛰므로, 키맵을 초기값으로 만들면 재로드가
;; 반영되지 않는다.
(define-key mrq-mode-command-map (kbd "s") #'mrq-mode-sync)
(define-key mrq-mode-command-map (kbd "p") #'mrq-mode-push)
(define-key mrq-mode-command-map (kbd "f") #'mrq-mode-pull)
(define-key mrq-mode-command-map (kbd "t") #'mrq-mode-toggle-state)
(define-key mrq-mode-command-map (kbd "r") #'mrq-mode-visit)
(define-key mrq-mode-map (kbd "C-c m") mrq-mode-command-map)

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

(defun mrq-mode--assert-current ()
  "이 버퍼가 `.mrq/current' 가 가리키는 MR 의 `review.md' 인지 확인한다.

`sync' 에는 `--mr' 이 없다 (`cli.md' §1).  `.mrq/3/review.md' 를 열어 두고
`pull --mr 9' 로 전환한 뒤 저장하면 **MR 9 가 sync 되고** MR 3 의 답글은
디스크에만 남아 다음 재렌더에 사라진다."
  (let ((mine (file-name-directory (file-truename (buffer-file-name))))
        (current (mrq-core-review-dir (buffer-file-name))))
    (unless (and current (equal (file-truename current) mine))
      (user-error
       "이 review.md 는 `.mrq/current' 가 가리키는 MR 이 아닙니다 — `mrq pull --mr %s' 로 전환한 뒤 여세요"
       (file-name-nondirectory (directory-file-name mine))))
    current))

(defun mrq-mode--assert-saved (what)
  "버퍼가 수정됐으면 WHAT 을 거부한다.

`pull'/`reanchor'/`push' 는 `review.md' 를 다시 쓴다 — 미저장 편집 위에
돌리면 작성 중인 답글이 사라진다."
  (when (buffer-modified-p)
    (user-error "먼저 저장하세요 — %s 는 review.md 를 다시 씁니다" what)))

(defun mrq-mode--after-save ()
  "`review.md' 를 저장하면 `mrq sync' 를 돌린다 (`editor.md' §3.3).

소스 파일 저장에는 아무것도 하지 않는다 — 이 훅은 `mrq-mode' 버퍼에만
걸리므로 그 구분이 자동으로 된다."
  (mrq-mode--assert-current)
  (mrq-mode--report (mrq-cli-run '("sync" "--json") nil (mrq-mode--repo-root))
                    :revert t))

(defun mrq-mode-sync ()
  "`mrq sync --json' 을 돌리고 결과에 따라 버퍼를 되읽는다.

버퍼가 수정됐으면 **저장만 한다** — `sync' 는 디스크의 md 를 읽으므로
저장하지 않고 부르면 CLI 가 옛 내용을 반영하고 재렌더가 작성 중인 답글을
덮어쓴다.  저장이 저장 훅을 통해 다시 여기로 들어온다."
  (interactive)
  (mrq-mode--assert-current)
  (if (buffer-modified-p)
      (save-buffer)
    (mrq-mode--report (mrq-cli-run '("sync" "--json") nil (mrq-mode--repo-root))
                      :revert t)))


;;;###autoload
(defun mrq-reanchor ()
  "`mrq reanchor --json'.  네트워크를 쓰지 않는다 (`cli.md' §6).

**소스 버퍼에서 부르는 명령이다** (`C-c m R').  소스를 고쳐 저장하면 json 의
`location' 이 낡는데, 버퍼 내 보정(`reanchoring.md' §6)은 창 200 줄 안의
유일한 후보만 잡으므로 큰 이동·파일 이동·rename 은 CLI 의 git 매핑이 필요하다.

`review.md' 버퍼에는 따로 키를 주지 않는다 — 거기서 저장하면 `sync' 가 어차피
재앵커링을 포함한다 (`cli.md' §5 4단계).

버퍼를 되읽지 않는다.  `review.json' 이 바뀌면 `file-notify' 가 열린 버퍼의
진단을 갱신하고(`editor.md' §1-5), `review.md' 를 보고 있다면 그쪽도 같은
경로로 처리된다."
  (interactive)
  (let ((root (or (mrq-core-root (buffer-file-name))
                  (user-error "리뷰가 있는 리포가 아닙니다"))))
    (mrq-mode--report (mrq-cli-run '("reanchor" "--json") nil root))))

(defun mrq-mode-pull ()
  "`mrq pull' 후 버퍼를 되읽는다."
  (interactive)
  (mrq-mode--assert-saved "pull")
  (mrq-mode--report (mrq-cli-run '("pull") nil (mrq-mode--repo-root))
                    :revert t))

(defun mrq-mode-push ()
  "`mrq status' 요약을 보여주고 확인을 받은 뒤 `mrq push'.

되돌릴 수 없는 작업이므로 확인을 받는다 — CLI 의 `prompt.confirm' 과 같은
규율이다."
  (interactive)
  (mrq-mode--assert-current)
  (mrq-mode--assert-saved "push")
  (let* ((root (mrq-mode--repo-root))
         (status (mrq-cli-run '("status" "--json") nil root)))
    (unless (= (plist-get status :code) 0)
      (mrq-mode--report status)
      (user-error "status 가 실패했습니다"))
    (when (yes-or-no-p (concat (mrq-mode--status-summary status)
                               "\npush 할까요? "))
      (mrq-mode--report (mrq-cli-run '("push" "--json") nil root) :revert t))))

(defun mrq-mode--status-summary (status)
  "STATUS(`mrq-cli-run' 의 결과)의 검토면을 한 줄로.

요약은 **stdout** 으로 나온다 (`cli.md' §2) — stderr 를 쓰면 보통 비어 있어
사용자가 되돌릴 수 없는 전송을 검토면 없이 승인하게 된다."
  (let* ((payload (plist-get status :json))
         (push (and payload (gethash "push" payload))))
    (if (not (hash-table-p push))
        (or (car (split-string (string-trim (plist-get status :stdout)) "\n"))
            "status 요약을 읽지 못했습니다")
      (format "replies %s · resolves %s · skipped %s"
              (gethash "replies" push)
              (gethash "resolves" push)
              (gethash "skipped" push)))))

(cl-defun mrq-mode--report (result &key revert)
  "RESULT 의 종료 코드에 따라 보고한다.

REVERT 가 non-nil 이고 성공이면 버퍼를 되읽는다.

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
  "exit 3 — PAYLOAD 로 충돌 버퍼를 띄운다.

버퍼는 되읽지 않는다 (CLI 가 아무것도 쓰지 않았다)."
  (require 'mrq-conflict)
  (mrq-conflict-show payload (mrq-core-review-dir (buffer-file-name)))
  (message "충돌 %d건 — %s 에서 고르세요"
           (length (gethash "conflicts" payload))
           mrq-conflict-buffer-name))

(defun mrq-mode--summary (result payload)
  "RESULT 와 PAYLOAD 로 에코 영역 한 줄을 만든다."
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
  "ITEM(`{line, message}')을 `review.md:<line>: <message>' 또는 평문으로."
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
답글을 쓸 때마다 일어난다.

두 가지를 함께 지킨다:

- 오프셋이 **그 블록을 넘지 않게** 자른다.  `sync' 는 답글을 정규형으로 다시
  쓰므로(`render.normalize_reply') 블록이 줄어드는 것이 정상 경로이고, 그대로
  두면 커서가 다음 스레드로 흘러간다.
- 앵커가 아예 사라졌으면(서버에서 resolve 돼 재렌더가 생략, `review-md.md' §5)
  **버퍼 맨 처음으로 보내지 않는다.**  답글을 쓰던 사용자가 문서 꼭대기로
  튕기는 것보다, 있던 줄 근처에 두는 쪽이 낫다."
  (let ((anchor (mrq-mode--thread-at-point))
        (line (line-number-at-pos))
        (column (current-column)))
    (revert-buffer t t t)
    (goto-char (point-min))
    (let ((last (line-number-at-pos (point-max))))
      (if (and anchor
               (re-search-forward
                (format "^<!-- mrq:%s " (regexp-quote (car anchor))) nil t))
          (progn
            (beginning-of-line)
            (let* ((head (line-number-at-pos))
                   (limit (save-excursion
                            (forward-line 1)
                            (if (re-search-forward mrq-mode-anchor-re nil t)
                                (1- (line-number-at-pos))
                              last))))
              (forward-line (- (min (+ head (cdr anchor)) limit) head))))
        (forward-line (1- (min line last)))))
    (move-to-column column)))


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
      ;; **같은 창**에서 연다.  다른 창에 띄우면 창 배치가 틀어져 혼란스럽고,
      ;; 돌아오는 길(`C-c m r' = `mrq-mode-visit')도 같은 창을 쓰므로 왕복이
      ;; 한 창 안에서 닫힌다.
      (pop-to-buffer-same-window (find-file-noselect md))
      (goto-char (point-min))
      (unless (re-search-forward (format "^<!-- mrq:%s " (regexp-quote id)) nil t)
        (user-error "%s 의 블록이 review.md 에 없습니다" id))
      (if (re-search-forward "^### reply$" nil t)
          (progn (forward-line 1)
                 (when (looking-at "^$") (forward-line 1)))
        (beginning-of-line)))))

(provide 'mrq-mode)
;;; mrq-mode.el ends here
