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

## 미리보기·PNG 저장

- PNG 변환은 `resvg-py`(pip wheel, 시스템 라이브러리 불필요)로 처리한다. 배포판 실행파일에는
  내장되어 있고, 소스 실행 시에는 `pip install resvg-py` 한 줄이면 된다.
- resvg-py가 없으면 cairosvg(있을 경우) → 브라우저 미리보기 순으로 자동 대체된다.
- 스캔 PDF·이미지 OCR을 쓰려면 `pymupdf`도 설치한다.

## 미리보기 인터랙션 (v0.3.1)

- **박스 클릭 1번** = 수정창 — 라벨(굵은 글씨)과 부제(작은 글씨)를 한 창에서 같이 수정.
  Enter=저장, 바깥 클릭=저장, Esc=취소, 🗑=완전 삭제(노드는 연결 화살표 포함).
  제목·하단 각주도 클릭으로 수정. AI 호출 없이 즉시 반영
- **화살표 클릭 1번** = 계수(라벨) 수정 · 실선/점선/측정 전환 · 🗑 삭제
- **Shift+박스 드래그** = 다른 박스로 끌어 새 화살표 추가
- **시작 화면** = 유형 6종 예시 갤러리 (썸네일 클릭 = 해당 유형 요청 문구 삽입,
  그린 뒤에도 "OO형으로 바꿔줘"로 전환 가능)
- 입력칸: **Enter=전송, Shift+Enter=줄바꿈**
- **Ctrl+Z (또는 [↩ 되돌리기] 버튼)** = 직전 편집 취소 — 화살표 추가/삭제, 이동,
  글자 수정, AI 재생성 전 상태까지 최근 50단계
- **박스 드래그** = 위치 이동 (자동 배치 위에 오프셋으로 기억, [배치 초기화]로 복원)
- **Ctrl+휠** = 미리보기 확대/축소, **빈 곳 드래그** = 이동
- **우하단 ◢ 드래그** = 출력 크기 배율 (SVG·PNG 저장 크기에 반영)

## 구조방정식(SEM) 표기 (v0.3)

path_model에서 노드 `kind:"latent"`(타원)·`"observed"`(관측지표, 상단 배치),
엣지 `style:"measure"`(가는 측정 화살표)를 지원한다. 경로계수는 edge label로 표시.

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
