# 도식화 챗봇 (v0.1)

문서/설명을 넣으면 AI가 도식 '설계도(JSON)'를 뽑고, 파이썬 렌더러가 공식으로
무채색 학술 SVG를 그려 주는 데스크톱 챗봇. 연구설계 챗봇의 형제 앱이다.

## 핵심 구조 (2단계)
1. **이해·설계 (AI, NVIDIA 무료 API)** — 문서 분석 → 도식 유형 판정 → JSON 스펙만 출력(그림 안 그림).
2. **렌더링 (파이썬, AI 없음)** — 좌표 공식으로 배치 → 대칭 자동 검증 → 무채색 집안 스타일 SVG.

이 분리로 대칭·정렬·집안 스타일·한자 차단을 코드로 보장한다.

## 실행 방법 (윈도우)

윈도우용 파이썬(python.org 배포판)에는 tkinter가 기본 포함된다.

```powershell
cd 소스코드
py -m pip install --user openai pypdf python-docx   # 최초 1회
py app.py
```

## 실행 방법 (macOS)

tkinter가 포함된 파이썬으로 실행해야 한다. macOS는 **시스템 파이썬**에 tkinter가 들어 있다.

```bash
cd "소스코드"
/usr/bin/python3 -m pip install --user openai pypdf python-docx   # 최초 1회
/usr/bin/python3 app.py
```

> pyenv/homebrew 파이썬에는 tkinter가 없을 수 있다. 그럴 때 `/usr/bin/python3`를 쓴다.

첫 실행 시 무료 NVIDIA API 키(nvapi-...)를 붙여넣는다. 키는 `~/.research-assistant.json`에
저장되며(연구설계 챗봇과 공유), 외부로 전송되지 않는다.

## 미리보기·PNG 저장 (선택)

- **SVG 저장**과 **브라우저 미리보기**는 추가 설치 없이 항상 작동한다(브라우저가 한글·벡터를 정확히 렌더).
- **앱 안 미리보기 이미지**와 **PNG 저장**은 `cairosvg`가 필요하다. macOS는 네이티브 cairo도 있어야 한다:
  ```bash
  brew install cairo
  /usr/bin/python3 -m pip install --user cairosvg
  ```
  설치가 없으면 앱은 자동으로 브라우저 미리보기로 대체한다(그림 품질은 동일).
- 스캔 PDF·이미지 OCR을 쓰려면 `pymupdf`도 설치한다.

## 지원 도식 유형 (v0.1)
분석틀(framework) · 계층/분류(tree) · 흐름/절차(flowchart) · 경로모형(path_model) ·
다차원 프로파일(radar) · 시계열 흐름(timeline).

## 모델
벤치마크(2026-07-01) 실측 결과 **GPT-OSS 120B**이 기본(빠름·구조 최상).
MiniMax M3(균형), DeepSeek V4 Pro(정밀·느림)도 툴바에서 선택 가능.

## 파일 구성
- `app.py` — Tkinter UI(좌: 지시/로그, 우: 미리보기·저장)
- `core.py` — 키·CJK검사·파일읽기·OCR·`get_spec`(JSON 완결 응답)
- `diagram_prompts.py` — 문서→JSON 스펙 시스템 프롬프트
- `renderer.py` — JSON 스펙→SVG(좌표 공식·대칭 검증·집안 스타일)
- `svg_export.py` — SVG 저장·PNG 변환·브라우저 미리보기
