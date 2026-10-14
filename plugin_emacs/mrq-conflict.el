;;; mrq-conflict.el --- 충돌 해소 버퍼 -*- lexical-binding: t -*-

;;; Commentary:
;;
;; `editor.md' §3.4.  `mrq sync' 의 exit 3 페이로드를 받아 스레드마다 방향을
;; 고르게 한다.
;;
;; **키를 누를 때마다 `sync' 를 부르지 않는다.**  `data-model.md' §5.3 이
;; "충돌이 하나라도 남으면 아무것도 쓰지 않고 exit 3" 을 MUST 로 두므로, 하나씩
;; 보내면 첫 키부터 실패한다.  `m'/`j' 는 표시만 하고 `C-c C-c' 가 모든 선택을
;; 한 번의 호출로 보낸다 — 부분 적용이 불가능하다는 것을 UI 가 그대로 반영한다.
;; 문법과 근거는 `docs/decisions/0013-scoped-conflict-resolution.md'.

;;; Code:

(require 'cl-lib)
(require 'subr-x)
(require 'mrq-cli)
(require 'mrq-core)

(defconst mrq-conflict-buffer-name "*mrq conflicts*"
  "충돌 해소 버퍼의 이름.")

(defconst mrq-conflict--entry-re "^\\([0-9a-f]\\{8,\\}\\)   →"
  "엔트리 머리글.")

(defvar-local mrq-conflict--entries nil
  "이 버퍼의 충돌들.  각 원소는 (ID CHOICE CONFLICT), CHOICE 는 nil/md/json.")

(defvar-local mrq-conflict--dir nil
  "`mrq sync' 를 돌릴 리뷰 디렉터리.")

(defvar mrq-conflict-mode-map
  (let ((map (make-sparse-keymap)))
    (define-key map (kbd "m") #'mrq-conflict-choose-md)
    (define-key map (kbd "j") #'mrq-conflict-choose-json)
    (define-key map (kbd "M") #'mrq-conflict-choose-all-md)
    (define-key map (kbd "J") #'mrq-conflict-choose-all-json)
    (define-key map (kbd "n") #'mrq-conflict-next)
    (define-key map (kbd "p") #'mrq-conflict-previous)
    (define-key map (kbd "C-c C-c") #'mrq-conflict-apply)
    (define-key map (kbd "q") #'quit-window)
    map)
  "`mrq-conflict-mode' 의 키맵.")

(define-derived-mode mrq-conflict-mode special-mode "MRQ-Conflict"
  "충돌을 스레드마다 해소한다."
  (setq-local truncate-lines nil))

;;;###autoload
(defun mrq-conflict-show (payload dir)
  "PAYLOAD(`sync --json' 의 exit 3 결과)를 DIR 기준 충돌 버퍼로 띄운다."
  (let ((buffer (get-buffer-create mrq-conflict-buffer-name)))
    (with-current-buffer buffer
      (mrq-conflict-mode)
      (setq mrq-conflict--dir dir)
      (setq mrq-conflict--entries
            (mapcar (lambda (c) (list (gethash "thread" c) nil c))
                    (gethash "conflicts" payload)))
      (mrq-conflict--render)
      (goto-char (point-min))
      (mrq-conflict--goto 0))
    (display-buffer buffer)
    buffer))

(defun mrq-conflict--render ()
  "엔트리들을 버퍼에 그린다."
  (let ((inhibit-read-only t))
    (erase-buffer)
    (insert "m: md 채택 · j: json 유지 · M/J: 전체 · C-c C-c: 적용 · q: 닫기\n"
            "선택이 남아 있으면 적용할 수 없습니다 — 부분 해소는 CLI 가 거부합니다.\n\n")
    (dolist (entry mrq-conflict--entries)
      (let* ((id (nth 0 entry))
             (choice (nth 1 entry))
             (conflict (nth 2 entry))
             (md (gethash "md" conflict))
             (json (gethash "json" conflict)))
        (insert (propertize id 'face 'bold)
                (format "   %s\n"
                        (propertize (pcase choice
                                      ('md "→ md")
                                      ('json "→ json")
                                      (_ "→ ?"))
                                    'face (if choice 'success 'warning)))
                (format "  md    [%s] %s\n"
                        (gethash "state" md)
                        (mrq-conflict--one-line (gethash "reply" md)))
                (format "  json  [%s] %s\n\n"
                        (gethash "state" json)
                        (mrq-conflict--one-line (gethash "reply" json))))))))

(defun mrq-conflict--one-line (text)
  "TEXT 의 첫 줄.  비어 있으면 빈 문자열."
  (if (or (null text) (string-empty-p text))
      ""
    (car (split-string text "\n"))))

(defun mrq-conflict--id-at-point ()
  "point 가 속한 엔트리의 thread id.  없으면 nil.

머리글 안내문 위에 있으면 **첫 엔트리**로 친다 — 거기서 `m' 을 눌렀을 때
에러를 내는 것보다 낫고, 아래쪽에는 안내문이 없으므로 모호하지 않다."
  (save-excursion
    (beginning-of-line)
    (cond
     ((looking-at mrq-conflict--entry-re) (match-string-no-properties 1))
     ((re-search-backward mrq-conflict--entry-re nil t)
      (match-string-no-properties 1))
     ((re-search-forward mrq-conflict--entry-re nil t)
      (match-string-no-properties 1)))))

(defun mrq-conflict--index ()
  "point 가 속한 엔트리의 0-기반 번호.  없으면 -1."
  (let ((id (mrq-conflict--id-at-point)))
    (if (null id)
        -1
      (or (cl-position id mrq-conflict--entries
                       :test #'equal :key (lambda (e) (nth 0 e)))
          -1))))

(defun mrq-conflict--goto (index)
  "INDEX 번째 엔트리로 point 를 옮긴다."
  (goto-char (point-min))
  (when (re-search-forward mrq-conflict--entry-re nil t (1+ index))
    (beginning-of-line)))

(defun mrq-conflict--choose (direction)
  "현재 엔트리를 DIRECTION 으로 표시한다.

다시 그린 뒤 **같은 엔트리로 돌아간다** — 커서가 처음으로 튀면 둘째 스레드를
고르기 전에 길을 잃는다."
  (let ((index (mrq-conflict--index)))
    (when (< index 0) (user-error "엔트리 위가 아닙니다"))
    (setf (nth 1 (nth index mrq-conflict--entries)) direction)
    (mrq-conflict--render)
    (mrq-conflict--goto index)))

(defun mrq-conflict-choose-md ()
  "현재 스레드를 md 채택으로 표시한다."
  (interactive)
  (mrq-conflict--choose 'md))

(defun mrq-conflict-choose-json ()
  "현재 스레드를 json 유지로 표시한다."
  (interactive)
  (mrq-conflict--choose 'json))

(defun mrq-conflict-choose-all-md ()
  "전부 md 채택으로 채운다.  개별 `m'/`j' 로 덮을 수 있다."
  (interactive)
  (mrq-conflict--choose-all 'md))

(defun mrq-conflict-choose-all-json ()
  "전부 json 유지로 채운다."
  (interactive)
  (mrq-conflict--choose-all 'json))

(defun mrq-conflict--choose-all (direction)
  "모든 엔트리를 DIRECTION 으로."
  (let ((index (max 0 (mrq-conflict--index))))
    (dolist (entry mrq-conflict--entries)
      (setf (nth 1 entry) direction))
    (mrq-conflict--render)
    (mrq-conflict--goto index)))

(defun mrq-conflict-next ()
  "다음 엔트리로."
  (interactive)
  (end-of-line)
  (if (re-search-forward mrq-conflict--entry-re nil t)
      (beginning-of-line)
    (user-error "마지막 엔트리입니다")))

(defun mrq-conflict-previous ()
  "이전 엔트리로."
  (interactive)
  (beginning-of-line)
  (if (re-search-backward mrq-conflict--entry-re nil t)
      (beginning-of-line)
    (user-error "첫 엔트리입니다")))

(defun mrq-conflict--sync-args ()
  "선택들을 `mrq sync' 인자 리스트로.

`--prefer <id>=md|json' 을 스레드마다 하나씩 준다.  스코프 없는 형태를 쓰지
않는 이유는 UI 가 모든 충돌에 명시적 선택을 요구하기 때문이다 — 생략하면
사용자가 `M' 로 채운 것인지 빠뜨린 것인지 인자에서 구별되지 않는다."
  (append '("sync" "--json")
          (mapcan (lambda (entry)
                    (list "--prefer" (format "%s=%s" (nth 0 entry) (nth 1 entry))))
                  mrq-conflict--entries)))

(defun mrq-conflict--close ()
  "충돌 버퍼를 닫는다.

창이 하나뿐이면 `quit-window' 를 쓰지 않는다 — 유일한 창을 지우려 들면
batch 에서 죽는다."
  (let ((buffer (current-buffer))
        (window (get-buffer-window (current-buffer))))
    (if (and window (not (one-window-p)))
        (quit-window t window)
      (kill-buffer buffer))))

(defun mrq-conflict-apply ()
  "모든 선택을 한 번의 `mrq sync' 로 보낸다.

고르지 않은 스레드가 남아 있으면 거부하고 그리로 point 를 옮긴다 — 부분
해소는 `data-model.md' §5.3 에 따라 전부 실패한다."
  (interactive)
  (let ((missing (cl-position nil mrq-conflict--entries :key (lambda (e) (nth 1 e)))))
    (when missing
      (mrq-conflict--goto missing)
      (user-error "아직 고르지 않은 스레드가 있습니다")))
  (let ((result (mrq-cli-run (mrq-conflict--sync-args) nil mrq-conflict--dir)))
    (if (= (plist-get result :code) 0)
        (progn
          (message "충돌 %d건을 해소했습니다" (length mrq-conflict--entries))
          (mrq-conflict--close))
      ;; 창을 닫지 않는다 — 닫으면 사용자가 선택을 처음부터 다시 해야 한다.
      (message "mrq sync 실패 (exit %d): %s"
               (plist-get result :code)
               (car (split-string (string-trim (plist-get result :stderr)) "\n"))))))

(provide 'mrq-conflict)
;;; mrq-conflict.el ends here
