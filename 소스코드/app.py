# -*- coding: utf-8 -*-
"""
app.py — 도식화 챗봇 (데스크탑 앱)
연구설계 챗봇의 UI 셸을 그대로 계승하되, 오른쪽에 '그림 미리보기 패널'을 붙였다.
문서/설명 입력 → AI가 도식 스펙(JSON) 산출 → 파이썬 렌더러가 무채색 SVG 생성 →
미리보기·SVG/PNG 저장·수정지시(부분 재렌더)까지.
각 사용자가 본인의 무료 NVIDIA 키를 입력해 사용한다(키는 본인 컴퓨터에만 저장).
"""

import os
import re
import json
import queue
import threading
import platform
import webbrowser
import subprocess
import tempfile
import base64
from datetime import datetime

import tkinter as tk
from tkinter import filedialog, messagebox

import core
import diagram_prompts
import renderer
import svg_export

# ── 데이터 저장 위치 ──
DATA_DIR = os.path.expanduser("~/Documents/DiagramChatbot")
OUT_DIR = os.path.join(DATA_DIR, "outputs")
TMP_DIR = os.path.join(DATA_DIR, "tmp")
os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(TMP_DIR, exist_ok=True)

# ── 어두운 테마 (연구설계 챗봇과 동일 팔레트) ──
C_BG = "#0d1117"
C_BG2 = "#161b22"
C_BORDER = "#30363d"
C_LINE = "#cdd5df"
C_TEXT = "#e6edf3"
C_DIM = "#8b949e"
C_GREEN = "#3fb950"
C_GREEN_D = "#2ea043"
C_GREEN_TX = "#3fb950"
C_BLUE = "#58a6ff"
C_AMBER = "#e3b341"
C_RED = "#f85149"
C_PREVIEW_BG = "#f4f4f4"   # 미리보기(그림) 배경 — 실제 그림은 흰 캔버스

# UI 글꼴: 맥은 고정폭(한글은 애플고딕으로 자연 폴백), 윈도우는 Consolas에 한글 글리프가
# 없어 굴림 계열로 떨어져 지저분해지므로 맑은 고딕을 직접 지정한다.
if platform.system() == "Darwin":
    MONO = "Menlo"
elif platform.system() == "Windows":
    MONO = "Malgun Gothic"
else:
    MONO = "DejaVu Sans Mono"

NVIDIA_URL = "https://build.nvidia.com"
APP_VERSION = "0.3.0"

DTYPE_LABELS = {
    "framework": "분석틀", "tree": "계층·분류", "flowchart": "흐름·절차",
    "path_model": "경로모형", "radar": "다차원 프로파일", "timeline": "시계열 흐름",
}

GUIDE_STEPS = [
    "1)  아래 [NVIDIA 사이트 열기]를 눌러 로그인 (구글·이메일)",
    "2)  화면 위에 Verify가 보이면 눌러 계정 인증",
    "3)  아무 모델이나 열기 (예: 검색창에 deepseek)",
    "4)  Build 탭의 [Generate API Key] 클릭",
    "5)  만들어진  nvapi-...  키를 [Copy]",
    "6)  아래 칸에 붙여넣고 [저장하고 시작]",
]

USAGE_TIPS = [
    "문서(PDF·docx·txt)를 📎로 첨부하거나, 아래에 연구 내용을 직접 써서 보내세요.",
    "예) \"교사 스트레스가 소진을 거쳐 교직 후회에 이르는 경로모형 그려줘\"",
    "그림이 나오면 미리보기에서 박스 더블클릭=글자 수정 · 드래그=위치 이동 · Ctrl+휠=확대,",
    "화살표 더블클릭=계수·점선/삭제 · Shift+박스 드래그=새 화살표 · 우하단 ◢=출력 크기.",
    "말로도 수정됩니다: \"3번 박스 이름 바꿔\"",
]


class _Tooltip:
    def __init__(self, widget, text):
        self.widget = widget; self.text = text; self.tip = None
        widget.bind("<Enter>", self.show, add="+")
        widget.bind("<Leave>", self.hide, add="+")

    def show(self, e=None):
        if self.tip:
            return
        x = self.widget.winfo_rootx() + 6
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 4
        self.tip = tw = tk.Toplevel(self.widget)
        tw.wm_overrideredirect(True)
        try:
            tw.wm_attributes("-topmost", True)
        except Exception:
            pass
        tk.Label(tw, text=self.text, bg="#1f2630", fg="#e6edf3", font=(MONO, 9),
                 padx=8, pady=4, relief="solid", bd=1).pack()
        tw.wm_geometry(f"+{x}+{y}")

    def hide(self, e=None):
        if self.tip:
            self.tip.destroy(); self.tip = None


class App(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("도식화 챗봇")
        self.configure(bg=C_BG)
        self.geometry("1040x720")
        self.minsize(880, 560)

        self.model_key = core.DEFAULT_MODEL
        self.client = None
        self.q = queue.Queue()
        self.busy = False
        self._cancel = False
        self.current_spec = None       # 마지막 도식 스펙(dict)
        self.current_svg = None        # 마지막 SVG 텍스트
        self.current_hits = []         # 노드 위치 지도(viewBox 좌표) — 클릭·드래그용
        self.current_edge_hits = []    # 화살표 선분 지도 — 클릭 편집용
        self.last_document = None      # 마지막으로 그린 원본 문서(재요청용)
        self._preview_img = None       # PhotoImage 참조 유지
        self._view_zoom = 1.0          # 미리보기 확대 배율(Ctrl+휠)
        self._pan = [0, 0]             # 미리보기 이동(빈 곳 드래그)
        self._img_origin = (0, 0)      # 캔버스 안 그림 좌상단 좌표
        self._px_per_unit = 1.0        # 캔버스 픽셀 / viewBox 단위
        self._drag = None              # 진행 중 드래그 상태
        self._hover_id = None          # 마우스 오버 중인 노드 id
        self._pending_keep = None      # 수정지시 시 유지할 offsets/size_scale

        key = core.load_key()
        if core.valid_key_format(key):
            self.client = core.make_client(key)
            self.build_main()
        else:
            self.build_onboarding()

    # ── 클립보드 단축키 (macOS 보완) ──
    def _enable_clipboard(self, w):
        for mod in ("Command", "Control"):
            w.bind(f"<{mod}-v>", lambda e: (e.widget.event_generate("<<Paste>>"), "break")[1])
            w.bind(f"<{mod}-c>", lambda e: (e.widget.event_generate("<<Copy>>"), "break")[1])
            w.bind(f"<{mod}-x>", lambda e: (e.widget.event_generate("<<Cut>>"), "break")[1])
            w.bind(f"<{mod}-a>", self._select_all_evt)

    def _select_all_evt(self, e):
        w = e.widget
        try:
            w.select_range(0, "end")
        except Exception:
            w.tag_add("sel", "1.0", "end-1c")
        return "break"

    def _btn(self, parent, text, cmd, fg=C_TEXT, bg=C_BG2, hover="#21262d", font=None, pady=6, padx=10):
        lbl = tk.Label(parent, text=text, fg=fg, bg=bg, cursor="hand2",
                       font=font or (MONO, 10), padx=padx, pady=pady)
        lbl.bind("<Button-1>", lambda e: cmd())
        lbl.bind("<Enter>", lambda e: lbl.configure(bg=hover))
        lbl.bind("<Leave>", lambda e: lbl.configure(bg=bg))
        return lbl

    # ════════ 온보딩 (키 입력) ════════
    def build_onboarding(self):
        for w in self.winfo_children():
            w.destroy()
        self.geometry("640x720")
        outer = tk.Frame(self, bg=C_BG, padx=26, pady=20)
        outer.pack(fill="both", expand=True)
        bottom = tk.Frame(outer, bg=C_BG)
        bottom.pack(side="bottom", fill="x")
        save_btn = tk.Label(bottom, text="저장하고 시작  ▸", bg=C_GREEN, fg="#0d1117",
                            font=(MONO, 14, "bold"), cursor="hand2", pady=12)
        save_btn.pack(fill="x", pady=(10, 0))
        save_btn.bind("<Button-1>", lambda e: self.save_and_start())
        save_btn.bind("<Enter>", lambda e: save_btn.configure(bg=C_GREEN_D))
        save_btn.bind("<Leave>", lambda e: save_btn.configure(bg=C_GREEN))

        top = tk.Frame(outer, bg=C_BG)
        top.pack(side="top", fill="both", expand=True)
        tk.Label(top, text="📊  사회과학 도식화 챗봇", bg=C_BG, fg=C_GREEN_TX,
                 font=(MONO, 19, "bold")).pack(pady=(6, 2))
        tk.Label(top, text="문서를 넣으면 학술 도식을 그려 줍니다 · 본인 키로 작동 · 완전 무료",
                 bg=C_BG, fg=C_DIM, font=(MONO, 10)).pack(pady=(0, 16))
        tk.Label(top, text="📋  무료 API 키 발급 방법 (약 3분)", bg=C_BG, fg=C_BLUE,
                 font=(MONO, 12, "bold")).pack(anchor="w")
        steps = tk.Frame(top, bg=C_BG2)
        steps.pack(fill="x", pady=(6, 10))
        for s in GUIDE_STEPS:
            tk.Label(steps, text=s, bg=C_BG2, fg=C_TEXT, font=(MONO, 11), justify="left",
                     anchor="w", wraplength=400, padx=12, pady=3).pack(fill="x")
        link = tk.Label(top, text="🔗  NVIDIA 사이트 열기  (build.nvidia.com)", bg=C_BG,
                        fg=C_BLUE, font=(MONO, 11, "underline"), cursor="hand2")
        link.pack(anchor="w", pady=(0, 16))
        link.bind("<Button-1>", lambda e: webbrowser.open(NVIDIA_URL))
        tk.Label(top, text="🔑  발급받은 API 키 붙여넣기", bg=C_BG, fg=C_TEXT,
                 font=(MONO, 11, "bold")).pack(anchor="w")
        self.key_entry = tk.Entry(top, bg="#ffffff", fg="#1A1A1A", insertbackground="#1A1A1A",
                                  font=(MONO, 12), relief="flat", highlightthickness=1,
                                  highlightbackground=C_BORDER, highlightcolor=C_BLUE)
        self.key_entry.pack(fill="x", ipady=8, pady=(6, 4))
        self.key_entry.focus_set()
        self._enable_clipboard(self.key_entry)
        tk.Label(top, text="🔒 이 키는 당신 컴퓨터에만 저장되며 외부로 전송되지 않습니다.",
                 bg=C_BG, fg=C_DIM, font=(MONO, 9), wraplength=400, justify="left").pack(anchor="w")

    def save_and_start(self):
        key = self.key_entry.get().strip()
        if not core.valid_key_format(key):
            messagebox.showerror("키 형식 오류",
                                 "키는 nvapi- 로 시작하는 영문/숫자여야 합니다.\n"
                                 "한글이나 빈칸이 섞이지 않았는지 확인하세요.")
            return
        core.save_key(key)
        self.client = core.make_client(key)
        self.build_main()

    # ════════ 메인 화면 (좌: 지시/로그, 우: 미리보기) ════════
    def build_main(self):
        for w in self.winfo_children():
            w.destroy()
        self.geometry("1040x720")

        # 툴바
        bar = tk.Frame(self, bg=C_BG2)
        bar.pack(fill="x")
        left = tk.Frame(bar, bg=C_BG2); left.pack(side="left", padx=8, pady=6)
        right = tk.Frame(bar, bg=C_BG2); right.pack(side="right", padx=8, pady=6)
        self.model_btn = self._btn(left, self._model_label(), self.open_model_menu, fg=C_GREEN_TX)
        self.model_btn.pack(side="left", padx=4)
        _Tooltip(self.model_btn, "도식 스펙을 만들 AI 모델 선택 (벤치마크 추천: GPT-OSS)")
        for txt, cmd, tip in [
            ("📎", self.attach_file, "문서 첨부(PDF·docx·txt) → 내용을 도식으로"),
            ("🔑", self.change_key, "API 키 변경"),
        ]:
            b = self._btn(right, txt, cmd, padx=9); b.pack(side="left", padx=5)
            _Tooltip(b, tip)
        tk.Frame(self, bg=C_BORDER, height=1).pack(side="top", fill="x")

        # 하단 입력 바
        ibar_outer = tk.Frame(self, bg=C_BG)
        ibar_outer.pack(side="bottom", fill="x", padx=10, pady=(4, 8))
        ibar = tk.Frame(ibar_outer, bg=C_BG2, highlightthickness=1,
                        highlightbackground=C_LINE, highlightcolor=C_LINE, bd=0)
        ibar.pack(fill="x")
        self.send_btn = tk.Label(ibar, text="그리기", bg=C_GREEN, fg="#0d1117",
                                 font=(MONO, 11, "bold"), cursor="hand2", padx=14)
        self.send_btn.pack(side="right", fill="y", padx=(4, 6), pady=6)
        self.send_btn.bind("<Button-1>", lambda e: self._on_send_click())
        self.bind("<Escape>", lambda e: self.cancel())
        tk.Label(ibar, text=" 입력 ▸", bg=C_BG2, fg=C_GREEN_TX,
                 font=(MONO, 11, "bold")).pack(side="left", anchor="n", pady=12)
        self.inp = tk.Text(ibar, bg=C_BG2, fg=C_TEXT, font=(MONO, 11), height=3, wrap="word",
                           relief="flat", bd=0, padx=6, pady=8, insertbackground=C_TEXT)
        self.inp.pack(side="left", fill="both", expand=True)
        self.inp.bind("<Return>", self.on_return)
        self.inp.bind("<FocusIn>", self._clear_ph)
        self.inp.bind("<FocusOut>", self._restore_ph)
        self._enable_clipboard(self.inp)
        self._ph_active = False
        self._set_ph()

        # 본문: 좌우 분할
        body = tk.Frame(self, bg=C_BG)
        body.pack(side="top", fill="both", expand=True, padx=10, pady=(8, 4))

        # 좌: 지시/로그
        lwrap = tk.Frame(body, bg=C_BG, width=360)
        lwrap.pack(side="left", fill="both", expand=False)
        lwrap.pack_propagate(False)
        lcard = tk.Frame(lwrap, bg=C_BG, highlightthickness=1,
                         highlightbackground=C_LINE, bd=0)
        lcard.pack(fill="both", expand=True)
        self.log = tk.Text(lcard, bg=C_BG, fg=C_TEXT, font=(MONO, 10), wrap="word",
                           relief="flat", bd=0, padx=10, pady=8, insertbackground=C_TEXT,
                           state="disabled", spacing1=2, spacing3=3)
        sb = tk.Scrollbar(lcard, command=self.log.yview)
        self.log.configure(yscrollcommand=sb.set)
        sb.pack(side="right", fill="y"); self.log.pack(side="left", fill="both", expand=True)
        self.log.tag_config("sys", foreground=C_DIM)
        self.log.tag_config("user", foreground=C_BLUE, font=(MONO, 10, "bold"))
        self.log.tag_config("h", foreground=C_GREEN_TX, font=(MONO, 11, "bold"))
        self.log.tag_config("warn", foreground=C_AMBER)
        self.log.tag_config("err", foreground=C_RED)

        # 우: 미리보기 + 저장 버튼
        rwrap = tk.Frame(body, bg=C_BG)
        rwrap.pack(side="left", fill="both", expand=True, padx=(10, 0))
        pv_bar = tk.Frame(rwrap, bg=C_BG)
        pv_bar.pack(side="bottom", fill="x", pady=(6, 0))
        for txt, cmd, tip in [
            ("SVG 저장", lambda: self.save_output("svg"), "벡터(SVG)로 저장 — 논문·PPT 확대해도 안 깨짐"),
            ("PNG 저장", lambda: self.save_output("png"), "이미지(PNG)로 저장"),
            ("브라우저 보기", self.open_browser, "시스템 브라우저로 크게 미리보기"),
            ("다시 그리기", self.redraw, "같은 내용으로 다시 그리기(재요청)"),
            ("새 도식", self.new_diagram, "현재 도식을 잊고 새 주제로 시작"),
            ("배치 초기화", self.reset_layout, "드래그 이동·크기 조절을 원래 자동 배치로 되돌림"),
        ]:
            b = self._btn(pv_bar, txt, cmd, bg=C_BG2, padx=10)
            b.pack(side="left", padx=(0, 6))
            _Tooltip(b, tip)
        self.preview = tk.Canvas(rwrap, bg=C_PREVIEW_BG, highlightthickness=0)
        self.preview.pack(side="top", fill="both", expand=True)
        self.preview.bind("<Configure>", lambda e: self._redraw_preview())
        self.preview.bind("<Control-MouseWheel>", self._on_pv_wheel)
        self.preview.bind("<ButtonPress-1>", self._on_pv_press)
        self.preview.bind("<Shift-ButtonPress-1>", self._on_pv_connect_press)
        self.preview.bind("<B1-Motion>", self._on_pv_motion)
        self.preview.bind("<ButtonRelease-1>", self._on_pv_release)
        self.preview.bind("<Double-Button-1>", lambda e: self._on_pv_double(e, "label"))
        self.preview.bind("<Shift-Double-Button-1>", lambda e: self._on_pv_double(e, "sub"))
        self.preview.bind("<Motion>", self._on_pv_hover)

        self._log("도식화 챗봇 준비 완료.", "h")
        self._log(f"모델: {core.MODEL_LABELS[self.model_key]}", "sys")
        for t in USAGE_TIPS:
            self._log("• " + t, "sys")
        if not svg_export.png_available():
            self._log("안내: 미리보기·PNG 저장은 resvg-py 설치 시 가능합니다: pip install resvg-py "
                      "(배포판 실행파일에는 내장 — SVG 저장·브라우저 보기는 지금도 가능)", "sys")

    # ════════ 모델 선택 ════════
    def _model_label(self):
        return f" 모델:{core.MODEL_LABELS[self.model_key]} ▾ "

    def open_model_menu(self):
        menu = tk.Menu(self, tearoff=0, bg=C_BG2, fg=C_TEXT, activebackground=C_GREEN,
                       activeforeground="#0d1117", font=(MONO, 10), bd=0)
        for k in core.MODELS:
            mark = "● " if k == self.model_key else "○ "
            menu.add_command(label=mark + core.MODEL_LABELS[k],
                             command=lambda kk=k: self.set_model(kk))
        x = self.model_btn.winfo_rootx(); y = self.model_btn.winfo_rooty() + self.model_btn.winfo_height()
        try:
            menu.tk_popup(x, y)
        finally:
            menu.grab_release()

    def set_model(self, k):
        self.model_key = k
        self.model_btn.configure(text=self._model_label())
        self._log(f"→ 모델 변경: {core.MODEL_LABELS[k]}", "sys")

    def change_key(self):
        if messagebox.askyesno("키 변경", "API 키를 다시 입력하시겠습니까?"):
            self.build_onboarding()

    # ════════ 입력 placeholder ════════
    # 주의: 한글 IME는 글자 조합 중 순간적으로 FocusOut/FocusIn을 발생시킬 수 있다.
    # 그래서 (1) 사용자 글자는 어떤 경로로도 지우지 않고(안내문구와 정확히 같을 때만 삭제),
    # (2) 안내문구 복원은 지연 후 포커스가 정말 떠났는지 확인하고 수행한다.
    PLACEHOLDER = "그리고 싶은 연구 내용·구조를 적어 주세요."

    def _set_ph(self):
        if self.inp.get("1.0", "end").strip():      # 내용(조합 중 글자 포함)이 있으면 덮지 않음
            return
        self.inp.delete("1.0", "end"); self.inp.insert("1.0", self.PLACEHOLDER)
        self.inp.configure(fg=C_DIM); self._ph_active = True

    def _clear_ph(self, e=None):
        if not getattr(self, "_ph_active", False):
            return
        # 안내문구가 그대로 있을 때만 지운다 — 사용자 글자는 절대 지우지 않는다
        if self.inp.get("1.0", "end-1c") == self.PLACEHOLDER:
            self.inp.delete("1.0", "end")
        self.inp.configure(fg=C_TEXT); self._ph_active = False

    def _restore_ph(self, e=None):
        self.after(150, self._restore_ph_check)

    def _restore_ph_check(self):
        try:
            focus = self.focus_get()
        except Exception:
            focus = None
        # 포커스가 아직 입력칸이거나 판정 불가(IME 순간 이탈)면 건드리지 않는다
        if focus is self.inp or focus is None:
            return
        self._set_ph()

    # ════════ 전송 ════════
    def on_return(self, event):
        self.send(); return "break"

    def _on_send_click(self):
        if self.busy:
            self.cancel()
        else:
            self.send()

    def send(self):
        if self.busy:
            return
        raw = self.inp.get("1.0", "end").strip()
        if not raw or raw == self.PLACEHOLDER:      # 안내문구는 전송하지 않음
            return
        text = raw
        self.inp.delete("1.0", "end")
        # 이미 그림이 있으면 '수정 지시'로 간주(부분 재렌더)
        if self.current_spec is not None and self._looks_like_edit(text):
            self._log("나 ▸ " + text, "user")
            self._start_spec(diagram_prompts.build_revise_user(
                json.dumps(self.current_spec, ensure_ascii=False), text),
                document=self.last_document, note="수정 반영 중…", keep_layout=True)
        else:
            self._log("나 ▸ " + text, "user")
            self._start_spec(diagram_prompts.build_spec_user(text),
                             document=text, note="도식 설계 중…")

    def _looks_like_edit(self, text):
        kws = ["바꿔", "수정", "고쳐", "지워", "빼", "추가", "이름", "색", "화살표", "노드", "박스", "라벨"]
        return any(k in text for k in kws)

    def new_diagram(self):
        """현재 도식·문서를 초기화 — 이후 입력은 수정지시가 아닌 새 도식 요청으로 처리."""
        if self.busy:
            return
        self.current_spec = None; self.current_svg = None; self.last_document = None
        self.current_hits = []; self.current_edge_hits = []
        self._preview_img = None
        self._view_zoom = 1.0; self._pan = [0, 0]
        self._redraw_preview()
        self._log("새 도식 — 다음 입력은 새 주제로 그립니다.", "sys")

    def redraw(self):
        if self.busy or not self.last_document:
            self._log("먼저 그릴 내용을 입력하세요.", "sys")
            return
        self._start_spec(diagram_prompts.build_spec_user(self.last_document),
                         document=self.last_document, note="다시 그리는 중…")

    # ════════ 파일 첨부 ════════
    def attach_file(self):
        if self.busy:
            return
        paths = self._ask_open(multiple=True, title="도식화할 문서 선택",
                               filetypes=[("지원 문서·이미지", "*.txt *.md *.pdf *.docx *.png *.jpg *.jpeg"),
                                          ("모든 파일", "*.*")])
        if not paths:
            return
        self.busy = True; self._cancel = False; self._set_stop()
        self._log("📎 파일 읽는 중… (스캔·이미지는 OCR로 처리)", "sys")
        threading.Thread(target=self._attach_worker, args=(list(paths),), daemon=True).start()
        self.after(80, self._poll_attach)

    def _attach_worker(self, paths):
        key = core.load_key(); parts, names = [], []
        for p in paths:
            if self._cancel:
                break
            base = os.path.basename(p)
            content, err = core.read_file_ocr(
                p, key, progress=lambda m, b=base: self.q.put(("prog", f"{b} — {m}")),
                should_cancel=lambda: self._cancel)
            if err:
                self.q.put(("warn", f"{base}: {err}")); continue
            parts.append(f"[파일: {base}]\n{content}"); names.append(base)
        self.q.put(("attached", ("\n\n".join(parts), names)))

    def _poll_attach(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "prog":
                    self._log("🔍 " + data, "sys")
                elif kind == "warn":
                    self._log("⚠️ " + data, "warn")
                elif kind == "attached":
                    doc, names = data
                    self.busy = False; self._set_go()
                    if not doc.strip():
                        self._log("읽어들인 내용이 없습니다.", "warn"); return
                    self._log(f"📎 {len(names)}개 문서 읽음 → 도식 설계 시작: {', '.join(names)}", "sys")
                    self._start_spec(diagram_prompts.build_spec_user(doc),
                                     document=doc, note="도식 설계 중…")
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.after(80, self._poll_attach)

    # ════════ 스펙 산출 → 렌더 ════════
    def _start_spec(self, user_content, document, note, keep_layout=False):
        self.busy = True; self._cancel = False; self._set_stop()
        self._anim_note = note; self._anim_i = 0
        self._log_anim_line = None
        self._pending_document = document
        # 수정지시일 때는 사용자가 드래그로 만든 배치·배율을 새 스펙에도 이어붙인다
        self._pending_keep = None
        if keep_layout and self.current_spec:
            keep = {k: self.current_spec[k] for k in ("offsets", "size_scale")
                    if k in self.current_spec}
            self._pending_keep = keep or None
        threading.Thread(target=self._spec_worker, args=(user_content,), daemon=True).start()
        self.after(60, self._poll_spec)
        self._animate()

    def _spec_worker(self, user_content):
        spec, raw, err = core.get_spec(self.client, self.model_key, user_content,
                                       should_cancel=lambda: self._cancel)
        self.q.put(("spec", (spec, raw, err)))

    def _animate(self):
        if not self.busy:
            return
        frames = ["", " ·", " · ·", " · · ·"]
        if not self._cancel:                      # 중지 중이면 "중지 중…" 표시를 덮지 않는다
            self.send_btn.configure(text="■ 중지")
        self._set_status(self._anim_note + frames[self._anim_i % 4])
        self._anim_i += 1
        self.after(400, self._animate)

    def _poll_spec(self):
        try:
            while True:
                kind, data = self.q.get_nowait()
                if kind == "spec":
                    self._finish_spec(*data)
                    return
        except queue.Empty:
            pass
        if self.busy:
            self.after(60, self._poll_spec)

    def _finish_spec(self, spec, raw, err):
        self.busy = False; self._set_go()
        self._clear_status()
        if self._cancel:
            self._cancel = False
            self._log("중지했습니다.", "sys"); return
        if err:
            self._log("⚠️ " + core.friendly_error(err), "err"); return
        if spec is None:
            self._log("⚠️ 도식 스펙을 만들지 못했습니다. 다시 시도해 주세요.", "err"); return

        # 한자/가나 검사(원문)
        cjk = core.check_cjk(json.dumps(spec, ensure_ascii=False))
        miss = renderer.missing_fields(spec)
        if miss:
            self._log("⚠️ 도식을 그리기에 정보가 부족합니다 (" + ", ".join(miss) + ").", "warn")
            self._log("어떤 개념·변수·단계가 들어가야 하는지 조금 더 구체적으로 적어 다시 보내 주세요.\n"
                      "예) \"학부모 스트레스와 업무 과부하가 소진을 거쳐 교직 후회로 이어지는 경로모형\"", "sys")
            return

        # 수정지시였다면 기존 드래그 배치·배율을 유지 (AI가 스펙에 남겼으면 그대로)
        if self._pending_keep:
            for k, v in self._pending_keep.items():
                spec.setdefault(k, v)
            self._pending_keep = None

        self.current_spec = spec
        self.last_document = self._pending_document
        svg, warns, hits, ehits = renderer.render(spec)
        self.current_svg = svg
        self.current_hits = hits
        self.current_edge_hits = ehits
        self._view_zoom = 1.0
        self._pan = [0, 0]

        dtype = spec.get("diagram_type", "?")
        self._log(f"■ 도식 완성: {DTYPE_LABELS.get(dtype, dtype)} "
                  f"(노드 {len(spec.get('nodes', []))}개)", "h")
        if spec.get("title"):
            self._log("제목: " + spec["title"], "sys")
        if cjk:
            self._log(f"⚠️ 한자/가나 의심 {len(cjk)}건 — {cjk[0]}", "warn")
        for w in warns:
            self._log("⚠️ " + w, "warn")
        self._log("미리보기: 더블클릭=글자 수정(화살표도) · 드래그=이동 · Shift+드래그=화살표 추가 · "
                  "Ctrl+휠=확대 · ◢=출력 크기. \"○○ 바꿔\"처럼 말로도 수정됩니다.", "sys")
        self._render_preview_from_svg(svg)
        self._notify("도식 완성", "도식 생성이 완료되었습니다.")

    # ════════ 미리보기 렌더 (Canvas) ════════
    def _viewbox_wh(self, svg):
        m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
        return (float(m.group(1)), float(m.group(2))) if m else (960.0, 560.0)

    def _pv_center_text(self, text):
        c = self.preview
        c.delete("all")
        c.create_text(max(10, c.winfo_width() / 2), max(10, c.winfo_height() / 2),
                      text=text, fill="#888888", font=(MONO, 11), justify="center")

    def _render_preview_from_svg(self, svg):
        self._redraw_preview()
        # 내장 미리보기가 불가하면, 첫 도식은 브라우저로 자동 열어 바로 보여준다
        if not svg_export.png_available() and not getattr(self, "_auto_browsed", False):
            self._auto_browsed = True
            self._log("↗ PNG 모듈이 없어 브라우저로 미리보기를 엽니다. (이후에는 [브라우저 보기] 버튼 사용)", "sys")
            self.open_browser()

    def _redraw_preview(self):
        c = self.preview
        svg = self.current_svg
        if not svg:
            self._pv_center_text("여기에 도식 미리보기가 표시됩니다.")
            return
        pw = max(60, c.winfo_width() - 8)
        ph = max(60, c.winfo_height() - 8)
        vw, vh = self._viewbox_wh(svg)
        disp = min(pw / vw, ph / vh) * self._view_zoom          # 화면픽셀/viewBox단위
        disp = max(0.05, min(disp, 6.0))
        size_scale = renderer.effective_size_scale(self.current_spec or {})
        png, err = svg_export.png_bytes(svg, scale=disp / size_scale)
        if err:
            self._pv_center_text("미리보기(PNG)에는 resvg-py가 필요합니다.\n"
                                 "[브라우저 보기]로 확인하거나  pip install resvg-py  후 사용하세요.\n"
                                 "(배포판 실행파일에는 내장되어 있습니다)")
            self._preview_img = None
            return
        try:
            img = tk.PhotoImage(data=base64.b64encode(png).decode())
        except Exception:
            self._pv_center_text("미리보기를 표시할 수 없습니다. [브라우저 보기]를 이용하세요.")
            self._preview_img = None
            return
        self._preview_img = img
        iw, ih = img.width(), img.height()
        ox = (c.winfo_width() - iw) / 2 + self._pan[0]
        oy = (c.winfo_height() - ih) / 2 + self._pan[1]
        self._img_origin = (ox, oy)
        self._px_per_unit = iw / vw
        c.delete("all")
        c.create_image(ox, oy, image=img, anchor="nw", tags="img")
        # 우하단 출력 크기 핸들(◢)
        hx, hy = ox + iw, oy + ih
        c.create_polygon(hx, hy - 14, hx, hy, hx - 14, hy,
                         fill="#8b949e", outline="", tags="szhandle")
        self._hover_id = None

    # ── 좌표 변환·판정 ──
    def _to_svg_xy(self, cx, cy):
        ox, oy = self._img_origin
        return (cx - ox) / self._px_per_unit, (cy - oy) / self._px_per_unit

    def _node_canvas_bbox(self, h):
        ox, oy = self._img_origin
        s = self._px_per_unit
        return (ox + h["x"] * s, oy + h["y"] * s,
                ox + (h["x"] + h["w"]) * s, oy + (h["y"] + h["h"]) * s)

    def _hit_at(self, cx, cy):
        x, y = self._to_svg_xy(cx, cy)
        for h in reversed(self.current_hits or []):
            if h["x"] <= x <= h["x"] + h["w"] and h["y"] <= y <= h["y"] + h["h"]:
                return h
        return None

    @staticmethod
    def _seg_dist(px, py, x1, y1, x2, y2):
        """점 (px,py)와 선분 (x1,y1)-(x2,y2) 사이 거리."""
        dx, dy = x2 - x1, y2 - y1
        L2 = dx * dx + dy * dy
        if L2 < 1e-9:
            return ((px - x1) ** 2 + (py - y1) ** 2) ** 0.5
        t = max(0.0, min(1.0, ((px - x1) * dx + (py - y1) * dy) / L2))
        qx, qy = x1 + t * dx, y1 + t * dy
        return ((px - qx) ** 2 + (py - qy) ** 2) ** 0.5

    def _edge_at(self, cx, cy):
        """캔버스 좌표에서 가장 가까운 화살표(허용오차 내)를 찾는다."""
        if not self.current_edge_hits:
            return None
        x, y = self._to_svg_xy(cx, cy)
        tol = max(7.0, 7.0 / max(self._px_per_unit, 0.1))
        best, best_d = None, tol
        for h in self.current_edge_hits:
            if h.get("ei", -1) < 0:
                continue
            d = self._seg_dist(x, y, h["x1"], h["y1"], h["x2"], h["y2"])
            if d < best_d:
                best_d, best = d, h
        return best

    def _on_size_handle(self, cx, cy):
        if not self._preview_img:
            return False
        ox, oy = self._img_origin
        hx, hy = ox + self._preview_img.width(), oy + self._preview_img.height()
        return (hx - 18) <= cx <= (hx + 4) and (hy - 18) <= cy <= (hy + 4)

    # ── 인터랙션: 줌·팬·드래그·더블클릭 수정 ──
    def _on_pv_wheel(self, e):
        if not self.current_svg:
            return
        factor = 1.1 if e.delta > 0 else 1 / 1.1
        self._view_zoom = max(0.2, min(4.0, self._view_zoom * factor))
        self._redraw_preview()

    def _on_pv_press(self, e):
        if not self.current_svg or self.busy:
            return
        c = self.preview
        if self._on_size_handle(e.x, e.y):
            self._drag = {"mode": "resize", "x0": e.x, "y0": e.y,
                          "scale0": renderer.effective_size_scale(self.current_spec or {})}
            return
        hit = self._hit_at(e.x, e.y)
        if hit and not str(hit["id"]).startswith("__"):   # 제목·각주는 드래그 아닌 더블클릭 수정
            gx1, gy1, gx2, gy2 = self._node_canvas_bbox(hit)
            ghost = c.create_rectangle(gx1, gy1, gx2, gy2, dash=(4, 3),
                                       outline="#1f6feb", width=2, tags="ghost")
            self._drag = {"mode": "node", "hit": hit, "x0": e.x, "y0": e.y, "ghost": ghost}
        else:
            self._drag = {"mode": "pan", "x0": e.x, "y0": e.y,
                          "pan0": (self._pan[0], self._pan[1])}

    def _on_pv_connect_press(self, e):
        """Shift+노드 드래그 = 새 화살표 추가 시작."""
        if not self.current_svg or self.busy:
            return
        hit = self._hit_at(e.x, e.y)
        if not hit or str(hit["id"]).startswith("__"):
            return "break"
        gx1, gy1, gx2, gy2 = self._node_canvas_bbox(hit)
        cx0, cy0 = (gx1 + gx2) / 2, (gy1 + gy2) / 2
        line = self.preview.create_line(cx0, cy0, e.x, e.y, dash=(4, 3),
                                        fill="#1f6feb", width=2, arrow="last", tags="cghost")
        self._drag = {"mode": "connect", "from": hit, "line": line,
                      "cx0": cx0, "cy0": cy0}
        return "break"

    def _on_pv_motion(self, e):
        d = self._drag
        if not d:
            return
        c = self.preview
        if d["mode"] == "node":
            gx1, gy1, gx2, gy2 = self._node_canvas_bbox(d["hit"])
            dx, dy = e.x - d["x0"], e.y - d["y0"]
            c.coords(d["ghost"], gx1 + dx, gy1 + dy, gx2 + dx, gy2 + dy)
        elif d["mode"] == "connect":
            c.coords(d["line"], d["cx0"], d["cy0"], e.x, e.y)
        elif d["mode"] == "pan":
            dx, dy = e.x - d["x0"], e.y - d["y0"]
            self._pan[0] = d["pan0"][0] + dx
            self._pan[1] = d["pan0"][1] + dy
            self._redraw_preview()
        elif d["mode"] == "resize":
            if not self._preview_img:
                return
            iw = self._preview_img.width()
            factor = max(0.3, 1.0 + (e.x - d["x0"]) / max(iw, 1))
            new_scale = max(0.5, min(2.5, d["scale0"] * factor))
            d["new_scale"] = new_scale
            c.delete("szinfo")
            ox, oy = self._img_origin
            c.create_rectangle(ox, oy, ox + iw * factor,
                               oy + self._preview_img.height() * factor,
                               dash=(4, 3), outline="#1f6feb", tags="szinfo")
            c.create_text(e.x + 8, e.y - 12, text=f"출력 배율 {new_scale:.2f}×",
                          anchor="w", fill="#1f6feb", font=(MONO, 10, "bold"), tags="szinfo")

    def _on_pv_release(self, e):
        d = self._drag
        self._drag = None
        if not d:
            return
        c = self.preview
        if d["mode"] == "node":
            c.delete("ghost")
            dx, dy = e.x - d["x0"], e.y - d["y0"]
            if abs(dx) < 3 and abs(dy) < 3:          # 이동 아님(단순 클릭)
                return
            s = self._px_per_unit
            nid = d["hit"]["id"]
            off = self.current_spec.setdefault("offsets", {})
            odx, ody = off.get(nid, [0, 0])
            off[nid] = [round(odx + dx / s, 1), round(ody + dy / s, 1)]
            self._rerender_local(f"노드 이동: {nid} (원위치는 [배치 초기화])")
        elif d["mode"] == "resize":
            c.delete("szinfo")
            if "new_scale" in d:
                self.current_spec["size_scale"] = round(d["new_scale"], 2)
                self._rerender_local(f"출력 크기 배율 {d['new_scale']:.2f}× — SVG·PNG 저장 크기에 반영")
        elif d["mode"] == "connect":
            c.delete("cghost")
            target = self._hit_at(e.x, e.y)
            src_id = d["from"]["id"]
            if (not target or str(target["id"]).startswith("__")
                    or target["id"] == src_id):
                return                                  # 빈 곳·자기 자신이면 취소
            spec = self.current_spec
            dup = next((ed for ed in spec.get("edges", [])
                        if ed.get("from") == src_id and ed.get("to") == target["id"]), None)
            if dup is None:
                spec.setdefault("edges", []).append(
                    {"from": src_id, "to": target["id"], "style": "solid"})
                self._rerender_local(f"화살표 추가: {src_id} → {target['id']}")
            new_ei = spec["edges"].index(dup if dup is not None else spec["edges"][-1])
            ehit = next((h for h in self.current_edge_hits if h.get("ei") == new_ei), None)
            if ehit:                                    # 바로 라벨·선 종류 정하게 수정창 열기
                self._begin_edge_edit(ehit)

    def _on_pv_double(self, e, field):
        if not self.current_svg or self.busy:
            return
        if self._drag:                                # press로 시작된 드래그 취소
            self.preview.delete("ghost"); self.preview.delete("cghost")
            self._drag = None
        hit = self._hit_at(e.x, e.y)
        if hit:
            self._begin_pv_edit(hit, field)
            return
        ehit = self._edge_at(e.x, e.y)
        if ehit:
            self._begin_edge_edit(ehit)

    def _begin_pv_edit(self, hit, field):
        spec = self.current_spec or {}
        nid = hit["id"]
        # 제목·각주는 스펙 최상위 필드를 직접 수정
        special_key = {"__title__": "title", "__caption__": "caption"}.get(nid)
        node = None
        if special_key is None:
            node = next((n for n in spec.get("nodes", []) if n.get("id") == nid), None)
            if node is None:
                return
            cur_val = node.get(field) or ""
            what = "부제" if field == "sub" else "라벨"
        else:
            cur_val = spec.get(special_key) or ""
            what = "제목" if special_key == "title" else "각주"
        c = self.preview
        gx1, gy1, gx2, gy2 = self._node_canvas_bbox(hit)
        wrap = tk.Frame(c, bg="#ffffff", relief="solid", bd=1)
        entry = tk.Entry(wrap, font=(MONO, 11), justify="center", bg="#ffffff",
                         fg="#1A1A1A", insertbackground="#1A1A1A", relief="flat", bd=0)
        entry.insert(0, cur_val)
        entry.pack(side="left", fill="both", expand=True, ipady=3, padx=(4, 0))
        del_btn = tk.Label(wrap, text="🗑", bg="#ffffff", fg=C_RED, cursor="hand2",
                           font=(MONO, 11), padx=6)
        del_btn.pack(side="right", fill="y")
        _Tooltip(del_btn, f"{what} 완전 삭제" + ("" if special_key else " (연결 화살표도 함께)"))
        win = c.create_window((gx1 + gx2) / 2, (gy1 + gy2) / 2, window=wrap,
                              width=max(170, gx2 - gx1 + 46))
        entry.focus_set(); entry.select_range(0, "end")
        self._enable_clipboard(entry)
        done_flag = {"done": False}

        def close():
            done_flag["done"] = True
            c.delete(win); wrap.destroy()

        def done(save):
            if done_flag["done"]:
                return
            val = entry.get().strip()
            close()
            if not save:
                return
            cjk = core.check_cjk(val)
            if cjk:
                self._log(f"⚠️ 입력에 한자/가나가 있습니다: {cjk[0]}", "warn")
            if special_key:
                if val:
                    spec[special_key] = val
                else:
                    spec.pop(special_key, None)
            elif field == "sub" and not val:
                node.pop("sub", None)
            else:
                node[field] = val
            self._rerender_local(f"{what} 수정: {val or '(삭제)'}")

        def delete_it(_e=None):
            if done_flag["done"]:
                return
            close()
            if special_key:
                spec.pop(special_key, None)
                self._rerender_local(f"{what} 삭제됨")
            else:
                spec["nodes"] = [n for n in spec.get("nodes", []) if n.get("id") != nid]
                spec["edges"] = [e for e in spec.get("edges", [])
                                 if e.get("from") != nid and e.get("to") != nid]
                (spec.get("offsets") or {}).pop(nid, None)
                self._rerender_local(f"노드 삭제: {node.get('label', nid)} (연결 화살표 포함)")

        del_btn.bind("<Button-1>", delete_it)

        def on_focus_out(ev):
            # 한글 IME가 조합 중 포커스를 순간적으로 뺏을 수 있으므로,
            # 잠시 뒤 포커스가 정말 떠났는지 확인한 뒤에만 (취소가 아니라) 저장하고 닫는다
            def check():
                if done_flag["done"]:
                    return
                try:
                    focus = self.focus_get()
                except Exception:
                    focus = None
                if focus is entry or focus is None:
                    return
                done(True)
            self.after(150, check)

        entry.bind("<Return>", lambda ev: done(True))
        entry.bind("<Escape>", lambda ev: done(False))
        entry.bind("<FocusOut>", on_focus_out)

    # ── 화살표(엣지) 편집: 라벨(계수)·실선/점선 전환·삭제 ──
    EDGE_STYLES = ["solid", "dashed", "measure"]
    EDGE_STYLE_LABEL = {"solid": "─ 실선", "dashed": "┄ 점선", "measure": "· 측정"}

    def _begin_edge_edit(self, ehit):
        spec = self.current_spec or {}
        edges = spec.get("edges", [])
        ei = ehit.get("ei", -1)
        if not (0 <= ei < len(edges)):
            return
        edge = edges[ei]
        c = self.preview
        ox, oy = self._img_origin
        s = self._px_per_unit
        ex = ox + (ehit["x1"] + ehit["x2"]) / 2 * s
        ey = oy + (ehit["y1"] + ehit["y2"]) / 2 * s
        wrap = tk.Frame(c, bg="#ffffff", relief="solid", bd=1)
        entry = tk.Entry(wrap, font=(MONO, 11), justify="center", bg="#ffffff",
                         fg="#1A1A1A", insertbackground="#1A1A1A", relief="flat", bd=0, width=12)
        entry.insert(0, edge.get("label") or "")
        entry.pack(side="left", fill="both", expand=True, ipady=3, padx=(4, 0))
        style_state = {"v": edge.get("style", "solid")}
        if style_state["v"] not in self.EDGE_STYLES:
            style_state["v"] = "solid"
        sty_btn = tk.Label(wrap, text=self.EDGE_STYLE_LABEL[style_state["v"]], bg="#eef2f6",
                           fg="#1A1A1A", cursor="hand2", font=(MONO, 10), padx=6)
        sty_btn.pack(side="left", fill="y", padx=(4, 0))
        _Tooltip(sty_btn, "클릭할 때마다 실선 → 점선 → 측정(가는 선) 전환")
        del_btn = tk.Label(wrap, text="🗑", bg="#ffffff", fg=C_RED, cursor="hand2",
                           font=(MONO, 11), padx=6)
        del_btn.pack(side="right", fill="y")
        _Tooltip(del_btn, "이 화살표 삭제")
        win = c.create_window(ex, ey, window=wrap, width=250)
        entry.focus_set(); entry.select_range(0, "end")
        self._enable_clipboard(entry)
        done_flag = {"done": False}

        def close():
            done_flag["done"] = True
            c.delete(win); wrap.destroy()

        def cycle_style(_e=None):
            i = self.EDGE_STYLES.index(style_state["v"])
            style_state["v"] = self.EDGE_STYLES[(i + 1) % len(self.EDGE_STYLES)]
            sty_btn.configure(text=self.EDGE_STYLE_LABEL[style_state["v"]])

        def done(save):
            if done_flag["done"]:
                return
            val = entry.get().strip()
            close()
            if not save:
                return
            if val:
                edge["label"] = val
            else:
                edge.pop("label", None)
            edge["style"] = style_state["v"]
            self._rerender_local(
                f"화살표 수정: {edge.get('from')}→{edge.get('to')} "
                f"({self.EDGE_STYLE_LABEL[style_state['v']].split()[-1]}"
                + (f", '{val}'" if val else "") + ")")

        def delete_it(_e=None):
            if done_flag["done"]:
                return
            close()
            try:
                spec["edges"].remove(edge)
            except ValueError:
                pass
            self._rerender_local(f"화살표 삭제: {edge.get('from')} → {edge.get('to')}")

        def on_focus_out(ev):
            def check():
                if done_flag["done"]:
                    return
                try:
                    focus = self.focus_get()
                except Exception:
                    focus = None
                if focus is entry or focus is None:
                    return
                done(True)
            self.after(150, check)

        sty_btn.bind("<Button-1>", cycle_style)
        del_btn.bind("<Button-1>", delete_it)
        entry.bind("<Return>", lambda ev: done(True))
        entry.bind("<Escape>", lambda ev: done(False))
        entry.bind("<FocusOut>", on_focus_out)

    def _on_pv_hover(self, e):
        if not self.current_svg or self._drag:
            return
        hit = self._hit_at(e.x, e.y)
        c = self.preview
        if self._on_size_handle(e.x, e.y):
            c.configure(cursor="bottom_right_corner")
            c.delete("hover"); self._hover_id = None
            return
        if hit is None:
            if self._hover_id is not None:
                c.delete("hover"); self._hover_id = None
            c.configure(cursor="hand2" if self._edge_at(e.x, e.y) else "")
            return
        c.configure(cursor="hand2")
        if hit["id"] != self._hover_id:
            c.delete("hover")
            c.create_rectangle(*self._node_canvas_bbox(hit), outline="#1f6feb",
                               width=1, dash=(2, 3), tags="hover")
            self._hover_id = hit["id"]

    def _rerender_local(self, msg=None):
        """AI 호출 없이 현재 스펙만 즉시 재렌더 (라벨 수정·드래그·배율)."""
        if not self.current_spec:
            return
        svg, warns, hits, ehits = renderer.render(self.current_spec)
        self.current_svg = svg
        self.current_hits = hits
        self.current_edge_hits = ehits
        for w in warns:
            self._log("⚠️ " + w, "warn")
        if msg:
            self._log("✏️ " + msg, "sys")
        self._redraw_preview()

    def reset_layout(self):
        """드래그 이동·출력 배율·미리보기 줌을 자동 배치 상태로 되돌린다."""
        if not self.current_spec:
            return
        self.current_spec.pop("offsets", None)
        self.current_spec.pop("size_scale", None)
        self._view_zoom = 1.0
        self._pan = [0, 0]
        self._rerender_local("배치·배율 초기화")

    def open_browser(self):
        if not self.current_svg:
            self._log("먼저 도식을 그려 주세요.", "sys"); return
        svg_export.open_in_browser(self.current_svg, TMP_DIR)

    # ════════ 저장 ════════
    def save_output(self, kind):
        if not self.current_svg:
            self._log("먼저 도식을 그려 주세요.", "sys"); return
        ts = datetime.now().strftime("%Y-%m-%d_%H%M")
        dtype = (self.current_spec or {}).get("diagram_type", "diagram")
        if kind == "svg":
            path = self._ask_save(title="SVG 저장", initialdir=OUT_DIR,
                                  initialfile=f"{ts}_{dtype}.svg", defaultextension=".svg",
                                  filetypes=[("SVG 벡터", "*.svg")])
            if not path:
                return
            svg_export.save_svg(self.current_svg, path)
            self._log(f"📤 SVG 저장됨: {path}", "sys"); self._open_file(path)
        else:
            if not svg_export.png_available():
                self._log("⚠️ PNG 저장에는 resvg-py가 필요합니다: pip install resvg-py "
                          "(배포판 실행파일에는 내장)", "warn"); return
            path = self._ask_save(title="PNG 저장", initialdir=OUT_DIR,
                                  initialfile=f"{ts}_{dtype}.png", defaultextension=".png",
                                  filetypes=[("PNG 이미지", "*.png")])
            if not path:
                return
            ok, err = svg_export.svg_to_png(self.current_svg, path, scale=2.0)
            if err:
                self._log("⚠️ " + err, "warn"); return
            self._log(f"📤 PNG 저장됨: {path}", "sys"); self._open_file(path)

    def _open_file(self, path):
        try:
            if platform.system() == "Darwin":
                subprocess.run(["open", path], check=False)
            elif platform.system() == "Windows":
                os.startfile(path)  # type: ignore[attr-defined]
            else:
                subprocess.run(["xdg-open", path], check=False)
        except Exception:
            webbrowser.open("file://" + path)

    # ════════ 공통 ════════
    def cancel(self):
        if self.busy:
            self._cancel = True
            self.send_btn.configure(text="중지 중…")

    def _set_stop(self):
        self.send_btn.configure(text="■ 중지", bg=C_RED, fg="#0d1117")

    def _set_go(self):
        self.send_btn.configure(text="그리기", bg=C_GREEN, fg="#0d1117")

    def _set_status(self, text):
        self.log.configure(state="normal")
        if getattr(self, "_log_anim_line", None):
            self.log.delete(self._log_anim_line, "end-1c")
        else:
            self.log.insert("end", "\n"); self._log_anim_line = self.log.index("end-1c")
        self.log.insert("end", "· " + text, "sys")
        self.log.see("end"); self.log.configure(state="disabled")

    def _clear_status(self):
        if getattr(self, "_log_anim_line", None):
            self.log.configure(state="normal")
            self.log.delete(self._log_anim_line, "end-1c")
            self.log.configure(state="disabled")
            self._log_anim_line = None

    def _log(self, text, tag="sys"):
        self.log.configure(state="normal")
        self.log.insert("end", "\n" + text, tag)
        self.log.see("end"); self.log.configure(state="disabled")

    def _ask_open(self, multiple=False, **kw):
        try:
            self.lift(); self.focus_force(); self.update_idletasks()
        except Exception:
            pass
        fn = filedialog.askopenfilenames if multiple else filedialog.askopenfilename
        return fn(parent=self, **kw)

    def _ask_save(self, **kw):
        try:
            self.lift(); self.focus_force(); self.update_idletasks()
        except Exception:
            pass
        return filedialog.asksaveasfilename(parent=self, **kw)

    def _notify(self, title, message):
        try:
            self.bell()
        except Exception:
            pass
        try:
            if platform.system() == "Darwin":
                subprocess.run(["osascript", "-e",
                                f'display notification "{message}" with title "{title}" sound name "Glass"'],
                               check=False, capture_output=True)
        except Exception:
            pass


def _macos_redraw_nudge(app):
    """macOS의 구버전 Tk에서 첫 화면이 그려지지 않고 빈 창으로 뜨는 문제 우회:
    창을 1px 늘렸다가 되돌려 강제로 다시 그리게 한다. 다른 OS에는 적용하지 않는다."""
    try:
        app.update_idletasks()
        wh, _, _ = app.geometry().partition("+")
        w, h = wh.split("x")
        app.geometry(f"{int(w) + 1}x{h}")
        app.after(60, lambda: app.geometry(f"{w}x{h}"))
    except Exception:
        pass


if __name__ == "__main__":
    _app = App()
    if platform.system() == "Darwin":
        _app.after(200, lambda: _macos_redraw_nudge(_app))
    _app.mainloop()
