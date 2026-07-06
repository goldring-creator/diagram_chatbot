# -*- coding: utf-8 -*-
"""
core.py — 도식화 챗봇 공통 엔진 (연구설계 챗봇 core.py의 형제 버전)
키 저장/로드·CJK 검사·파일 읽기·OCR는 그대로 이식하고,
'글 스트리밍' 대신 '도식 스펙(JSON) 완결 응답'을 받는 get_spec()으로 분기한다.
개발자 키를 하드코딩하지 않는다. 사용자가 입력한 키만 사용한다.
"""

import os
import re
import json
import time
import base64
import urllib.request
import urllib.error
from html.parser import HTMLParser

from openai import OpenAI
import diagram_prompts

# ── 설정(키) 저장 위치: 사용자 홈 폴더 (연구설계 챗봇과 공유) ──
CONFIG_PATH = os.path.expanduser("~/.research-assistant.json")

# ── 모델 (벤치마크 실측 결과 순 — 2026-07-01) ──
# gpt-oss-120b: 평균 10.9초·9노드·구조 최상 → 기본. minimax 균형, deepseek 정밀.
MODELS = {
    "gpt-oss":  "openai/gpt-oss-120b",
    "minimax":  "minimaxai/minimax-m3",
    "deepseek": "deepseek-ai/deepseek-v4-pro",
}
MODEL_LABELS = {
    "gpt-oss":  "GPT-OSS 120B (빠름·추천)",
    "minimax":  "MiniMax M3 (균형)",
    "deepseek": "DeepSeek V4 Pro (정밀·느림)",
}
DEFAULT_MODEL = "gpt-oss"

BASE_URL = "https://integrate.api.nvidia.com/v1"

SUPPORTED_NOTE = "읽기 지원: PDF · Word(.docx) · HTML · 텍스트(.txt /.md)   ·   한글(.hwp /.hwpx)은 지원 제한"


class _HTMLText(HTMLParser):
    """HTML에서 본문 텍스트만 추출 (script/style 제외, 블록 요소는 줄바꿈)."""
    # meta·link 같은 void 요소는 닫는 태그가 없어 _SKIP에 넣으면 깊이가 영영 안 내려옴
    _SKIP = {"script", "style", "head", "noscript"}
    _BLOCK = {"p", "div", "br", "li", "tr", "h1", "h2", "h3", "h4", "h5", "h6",
              "table", "section", "article", "ul", "ol", "blockquote"}

    def __init__(self):
        super().__init__()
        self._skip_depth = 0
        self.parts = []

    def handle_starttag(self, tag, attrs):
        if tag in self._SKIP:
            self._skip_depth += 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_endtag(self, tag):
        if tag in self._SKIP and self._skip_depth > 0:
            self._skip_depth -= 1
        elif tag in self._BLOCK:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip_depth and data.strip():
            self.parts.append(data)

    def text(self) -> str:
        out = "".join(self.parts)
        return re.sub(r"\n{3,}", "\n\n", out).strip()


def _read_text_any(path: str) -> str:
    """텍스트 파일을 인코딩 폴백(utf-8-sig → cp949 → euc-kr)으로 읽는다."""
    for enc in ("utf-8-sig", "cp949", "euc-kr"):
        try:
            with open(path, "r", encoding=enc) as f:
                return f.read()
        except UnicodeDecodeError:
            continue
    with open(path, "r", encoding="utf-8", errors="ignore") as f:
        return f.read()


def _read_html(path: str) -> str:
    raw = _read_text_any(path)
    p = _HTMLText()
    p.feed(raw)
    return p.text()


# ── 키 저장/로드 ──
def load_key() -> str:
    if os.path.exists(CONFIG_PATH):
        try:
            with open(CONFIG_PATH, "r", encoding="utf-8") as f:
                return json.load(f).get("api_key", "")
        except Exception:
            return ""
    return ""


def save_key(key: str):
    """키 저장. 성공하면 None, 실패하면 오류 메시지 문자열."""
    try:
        with open(CONFIG_PATH, "w", encoding="utf-8") as f:
            json.dump({"api_key": key.strip()}, f, ensure_ascii=False)
    except OSError as e:
        return f"키 파일을 저장할 수 없습니다: {e}"
    try:
        os.chmod(CONFIG_PATH, 0o600)   # 다중 사용자 환경 노출 방지 (윈도우는 사실상 무시됨)
    except OSError:
        pass
    return None


def valid_key_format(key: str) -> bool:
    key = (key or "").strip()
    return key.startswith("nvapi-") and len(key) > 20 and key.isascii()


def make_client(key: str) -> OpenAI:
    # timeout 미지정 시 SDK 기본 600초 — 그동안 '중지'가 듣지 않으므로 명시한다
    return OpenAI(base_url=BASE_URL, api_key=key.strip(), timeout=120.0)


# ── 한자/가나 오염 검사 ──
def check_cjk(text: str) -> list:
    found = []
    for i, ch in enumerate(text):
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            ctx = text[max(0, i - 6):i + 6].replace("\n", " ")
            found.append(f"'{ch}'(U+{code:04X}) …{ctx}…")
    return found


# ── 파일 → 텍스트 (pypdf / python-docx) ──
def read_file(path: str):
    path = os.path.expanduser(path.strip().strip('"').strip("'"))
    if not os.path.exists(path):
        return None, f"파일을 찾을 수 없습니다: {os.path.basename(path)}"
    ext = os.path.splitext(path)[1].lower()
    try:
        if ext in (".txt", ".md"):
            # utf-8만 쓰면 cp949(옛 메모장 기본) 문서의 한글이 통째로 소실된다
            return _read_text_any(path), None
        if ext in (".html", ".htm"):
            text = _read_html(path)
            if not text:
                return None, "HTML에서 본문 텍스트를 찾지 못했습니다."
            return text, None
        if ext == ".pdf":
            from pypdf import PdfReader
            with open(path, "rb") as fh:
                reader = PdfReader(fh)
                text = "\n".join((p.extract_text() or "") for p in reader.pages).strip()
            if not text:
                return None, "이미지로 스캔된 PDF로 보입니다 — 텍스트를 추출할 수 없습니다."
            return text, None
        if ext == ".docx":
            import docx
            d = docx.Document(path)
            return "\n".join(p.text for p in d.paragraphs), None
        if ext in (".hwp", ".hwpx"):
            return None, ("한글 파일(.hwp/.hwpx)은 현재 지원되지 않습니다. "
                          "한글에서 'PDF로 저장' 후 PDF를 첨부해 주세요.")
        return None, f"지원하지 않는 형식입니다: {ext} (PDF·docx·html·txt·md만 가능)"
    except Exception as e:
        return None, f"파일 읽기 오류: {e}"


# ── OCR (스캔 PDF·이미지 → 텍스트) : NVIDIA nemotron-ocr-v2 ──
OCR_URL = "https://ai.api.nvidia.com/v1/cv/nvidia/nemotron-ocr-v2"
OCR_MAX_PAGES = 30
OCR_PAGE_GAP = 1.6
IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif")


def _load_fitz():
    try:
        import pymupdf
        return pymupdf
    except Exception:
        try:
            import fitz
            return fitz
        except Exception:
            return None


def ocr_image_bytes(key: str, img_bytes: bytes):
    b64 = base64.b64encode(img_bytes).decode()
    body = {"input": [{"type": "image_url", "url": f"data:image/png;base64,{b64}"}]}
    req = urllib.request.Request(
        OCR_URL, data=json.dumps(body).encode(),
        headers={"Authorization": f"Bearer {key.strip()}",
                 "Content-Type": "application/json", "Accept": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=90) as r:
            data = json.loads(r.read())
    except urllib.error.HTTPError as e:
        try:
            detail = e.read().decode("utf-8", "ignore")
        except Exception:
            detail = ""
        return None, f"OCR 오류 {e.code}: {detail[:200]}"
    except Exception as e:
        return None, f"OCR 연결 오류: {e}"

    lines = []
    for item in data.get("data", []):
        dets = item.get("text_detections", [])

        def order(d):
            pts = d.get("bounding_box", {}).get("points", [])
            ys = [p.get("y", 0) for p in pts] or [0]
            xs = [p.get("x", 0) for p in pts] or [0]
            return (round(min(ys), 2), min(xs))

        for d in sorted(dets, key=order):
            t = d.get("text_prediction", {}).get("text", "")
            if t:
                lines.append(t)
    return "\n".join(lines), None


def _render_under_limit(page, limit=170000) -> bytes:
    fitz = _load_fitz()
    last = None
    for dpi in (220, 170, 130, 100, 75):
        pix = page.get_pixmap(dpi=dpi, colorspace=fitz.csGRAY)
        last = pix.tobytes("png")
        if len(last) <= limit:
            return last
    return last


def read_file_ocr(path: str, key: str, progress=None, should_cancel=None):
    path = os.path.expanduser(path.strip().strip('"').strip("'"))
    if not os.path.exists(path):
        return None, f"파일을 찾을 수 없습니다: {os.path.basename(path)}"
    ext = os.path.splitext(path)[1].lower()

    if ext in IMAGE_EXTS:
        fitz = _load_fitz()
        if fitz is None:
            return None, "이미지 OCR 구성요소(PyMuPDF)가 설치되어 있지 않습니다."
        if progress:
            progress("이미지 OCR 처리 중…")
        doc = None
        try:
            doc = fitz.open(path)
            img = _render_under_limit(doc.load_page(0))
        except Exception as e:
            return None, f"이미지 열기 오류: {e}"
        finally:
            if doc is not None:
                doc.close()
        text, err = ocr_image_bytes(key, img)
        if err:
            return None, err
        if not (text or "").strip():
            return None, "이미지에서 글자를 찾지 못했습니다."
        return text, None

    if ext == ".pdf":
        text, _err = read_file(path)
        if text and text.strip():
            return text, None
        return _ocr_pdf(path, key, progress, should_cancel)

    return read_file(path)


def _ocr_pdf(path, key, progress=None, should_cancel=None):
    fitz = _load_fitz()
    if fitz is None:
        return None, "스캔 PDF OCR 구성요소(PyMuPDF)가 설치되어 있지 않습니다."
    try:
        doc = fitz.open(path)
        total = doc.page_count
    except Exception as e:
        return None, f"PDF 열기 오류: {e}"

    pages = min(total, OCR_MAX_PAGES)
    out = []
    try:
        for i in range(pages):
            if should_cancel and should_cancel():
                return None, "사용자가 중지했습니다."
            if progress:
                progress(f"스캔 문서 OCR 처리 중… ({i + 1}/{pages}쪽)")
            try:
                img = _render_under_limit(doc.load_page(i))
            except Exception as e:
                return None, f"{i + 1}쪽 렌더링 오류: {e}"
            text, err = ocr_image_bytes(key, img)
            if err and _is_rate_limit(err):
                time.sleep(20)
                text, err = ocr_image_bytes(key, img)
            if err:
                return None, err
            if text:
                out.append(text)
            if i < pages - 1:
                time.sleep(OCR_PAGE_GAP)
    finally:
        doc.close()

    result = "\n\n".join(out).strip()
    if not result:
        return None, "OCR로 텍스트를 추출하지 못했습니다."
    if total > pages:
        result += f"\n\n[안내: 분량이 많아 처음 {pages}쪽만 OCR 처리했습니다. (전체 {total}쪽)]"
    return result, None


# ── 오류 메시지 한글 변환 ──
def friendly_error(raw: str) -> str:
    s = str(raw)
    low = s.lower()
    if "429" in s or "too many requests" in low:
        return "요청이 잠시 많아 한도(분당 40회)에 걸렸습니다. 1분쯤 기다린 뒤 다시 보내 주세요."
    if "401" in s or "unauthorized" in low or "invalid api key" in low:
        return "API 키가 올바르지 않거나 만료되었습니다. 우측 상단 열쇠 버튼에서 키를 다시 입력해 주세요."
    if "403" in s or "forbidden" in low:
        return "이 키로는 해당 모델에 접근할 수 없습니다. NVIDIA 계정의 키 권한을 확인해 주세요."
    if "404" in s or "not found" in low:
        return "모델을 찾을 수 없습니다. 모델 이름이 바뀌었거나 종료되었을 수 있습니다."
    if "500" in s or "502" in s or "503" in s or "internal server" in low or "service unavailable" in low:
        return "NVIDIA 서버가 일시적으로 불안정합니다. 잠시 후 다시 시도해 주세요."
    if "timeout" in low or "timed out" in low:
        return "응답 시간이 초과되었습니다. 네트워크를 확인하고 다시 시도해 주세요."
    if "connection" in low or "network" in low or "getaddrinfo" in low:
        return "인터넷 연결을 확인해 주세요. 네트워크에 연결되지 않은 것 같습니다."
    return f"문제가 발생했습니다. 잠시 후 다시 시도해 주세요. (상세: {s[:120]})"


RETRY_WAITS = [15, 30, 60]


def _is_rate_limit(msg: str) -> bool:
    low = str(msg).lower()
    return "429" in str(msg) or "too many requests" in low


# ── JSON 추출 (모델 응답에서 첫 '{' ~ 마지막 '}') ──
def extract_json(text: str):
    if not text:
        return None
    text = text.strip()
    text = re.sub(r"^```[a-zA-Z]*", "", text).strip().rstrip("`").strip()
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except Exception:
        return None


# ── 도식 스펙 산출 (스트리밍 아님 — JSON 완결 응답) ──
def get_spec(client, model_key, user_content, should_cancel=None):
    """문서/설명 또는 수정요청 → 도식 스펙(JSON dict). (spec_dict, raw_text, err) 반환.
    부분 JSON은 파싱 불가하므로 스트리밍을 쓰지 않는다. 429는 자동 재시도한다."""
    system = diagram_prompts.build_spec_system()
    kwargs = dict(
        model=MODELS[model_key],
        messages=[{"role": "system", "content": system},
                  {"role": "user", "content": user_content}],
        temperature=0.3, top_p=0.9, max_tokens=4096, stream=False,
    )
    if model_key == "deepseek":
        kwargs["extra_body"] = {"chat_template_kwargs": {"thinking": False}}

    json_retried = False   # JSON 재요청(1회)과 429 대기 횟수는 별도로 센다
    rate_tries = 0
    while True:
        if should_cancel and should_cancel():
            return None, "", "사용자가 중지했습니다."
        try:
            resp = client.chat.completions.create(**kwargs)
            choice = resp.choices[0]
            text = choice.message.content or ""
            spec = extract_json(text)
            if spec is None:
                # 출력이 길이 제한에 잘린 경우: 재요청해도 또 잘리므로 바로 안내
                if getattr(choice, "finish_reason", "") == "length":
                    return None, text, ("도식이 너무 커서 응답이 잘렸습니다. "
                                        "문서를 나누거나 핵심 부분만 다시 시도해 주세요.")
                # 한 번 더 강하게 JSON만 요청 (직전 응답을 대화에 포함해야 모델이 참조 가능)
                if not json_retried:
                    json_retried = True
                    kwargs["messages"].append({"role": "assistant", "content": text})
                    kwargs["messages"].append(
                        {"role": "user",
                         "content": "방금 응답에서 유효한 JSON 객체 하나만, 코드블록 없이 다시 출력해."})
                    continue
                return None, text, "모델이 유효한 JSON을 내지 못했습니다. 다시 시도해 주세요."
            return spec, text, None
        except Exception as e:
            msg = str(e)
            if _is_rate_limit(msg) and rate_tries < len(RETRY_WAITS):
                # 통짜 sleep이면 '중지'가 최대 60초 늦게 듣는다 — 1초 단위로 취소 확인
                for _ in range(RETRY_WAITS[rate_tries]):
                    if should_cancel and should_cancel():
                        return None, "", "사용자가 중지했습니다."
                    time.sleep(1)
                rate_tries += 1
                continue
            return None, "", msg
