# -*- coding: utf-8 -*-
"""
모델비교_벤치마크.py — 도식화 챗봇용 NVIDIA 무료 LLM 실측 비교

무엇을 재나:
  같은 '문서 → 도식 JSON 스펙' 과제를 여러 무료 모델에 던져
  (1) 유효한 JSON을 냈는가  (2) 필수 스키마 필드를 지켰는가
  (3) 한자/가나 오염이 없는가  (4) 첫 응답까지 걸린 시간(초)
  을 표로 비교한다. 점수 높고 빠른 모델을 하나 고르기 위한 것.

쓰는 법:
  1) NVIDIA 무료 키 준비(nvapi-...). build.nvidia.com 에서 2분이면 발급.
  2) 터미널에서:  set NVIDIA_API_KEY=nvapi-xxxx   (윈도우 CMD)
     또는 파워셸:  $env:NVIDIA_API_KEY="nvapi-xxxx"
  3) python 모델비교_벤치마크.py
  키를 환경변수로 안 주면, 기존 앱 키파일(~/.research-assistant.json)도 자동으로 찾는다.

주의: 분당 40회 제한이 있으므로 모델 사이에 잠깐씩 쉰다.
"""

import os
import io
import re
import sys
import json
import time

# 콘솔 한글 출력 안전장치(윈도우)
try:
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
except Exception:
    pass

from openai import OpenAI

BASE_URL = "https://integrate.api.nvidia.com/v1"

# ── 비교할 무료 모델 (크레딧 없이 쓰는 후보) ─────────────────────
# 이름이 바뀌거나 종료될 수 있으니, 404가 나면 build.nvidia.com/models 에서 현행 이름 확인.
MODELS = {
    "deepseek-v4-pro":   "deepseek-ai/deepseek-v4-pro",
    "deepseek-v4-flash": "deepseek-ai/deepseek-v4-flash",
    "qwen3.5-397b":      "qwen/qwen3.5-397b-a17b",
    "qwen3.5-122b":      "qwen/qwen3.5-122b-a10b",
    "minimax-m3":        "minimaxai/minimax-m3",
    "nemotron-super1.5": "nvidia/llama-3.3-nemotron-super-49b-v1.5",
    "gpt-oss-120b":      "openai/gpt-oss-120b",
}

# ── 도식 스펙 스키마를 강제하는 시스템 프롬프트(챗봇 본체와 동일 계약) ──
SYSTEM = """너는 사회과학 논문 도식 설계자다. 그림을 그리지 말고, 도식 설계도(JSON) 하나만 낸다.
반드시 한국어로만 쓴다. 한자나 일본어 가나를 절대 섞지 않는다.
설명·코드블록 표시(```) 없이 유효한 JSON 객체 하나만 출력한다.
스키마:
{
  "diagram_type": "framework|tree|flowchart|path_model|radar|timeline 중 하나",
  "title": "제목",
  "nodes": [ {"id":"...", "label":"짧은 라벨", "sub":"부제(선택)", "role":"emphasis|normal|ghost"} ],
  "edges": [ {"from":"id", "to":"id", "style":"solid|dashed", "label":""} ],
  "caption": "하단 각주(선택)"
}
문서에 없는 노드·수치를 지어내지 않는다. 근거가 약한 노드는 role을 ghost로 표시한다."""

# ── 테스트 과제(짧은 연구 설명 → 트리형 분석틀 기대) ─────────────
TASK = """다음 연구 설명을 도식 설계도(JSON)로 바꿔라.

연구 개요: 교원의 직무 스트레스가 교직 후회에 미치는 영향을 본다. 상위 개념은
'직무 요구-자원(JD-R) 이론'이다. 직무 요구 쪽에는 학부모 스트레스와 업무 과부하가 있고,
직무 자원 쪽에는 동료 지원과 자율성이 있다. 직무 요구는 소진을 높여 교직 후회를 키우고,
직무 자원은 소진을 낮춰 교직 후회를 줄인다. 소진이 매개 변수다."""

REQUIRED_KEYS = ("diagram_type", "nodes", "edges")
VALID_TYPES = {"framework", "tree", "flowchart", "path_model", "radar", "timeline"}


def find_key() -> str:
    k = os.environ.get("NVIDIA_API_KEY", "").strip()
    if k:
        return k
    cfg = os.path.expanduser("~/.research-assistant.json")
    if os.path.exists(cfg):
        try:
            with open(cfg, encoding="utf-8") as f:
                return json.load(f).get("api_key", "").strip()
        except Exception:
            pass
    return ""


def has_cjk(text: str) -> bool:
    for ch in text:
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            return True
    return False


def extract_json(text: str):
    """응답에서 첫 '{' ~ 마지막 '}' 사이를 잘라 JSON 파싱을 시도한다."""
    if not text:
        return None
    text = text.strip()
    # 코드블록 감싸기 제거
    text = re.sub(r"^```[a-zA-Z]*", "", text).strip().rstrip("`").strip()
    a, b = text.find("{"), text.rfind("}")
    if a == -1 or b == -1 or b <= a:
        return None
    try:
        return json.loads(text[a:b + 1])
    except Exception:
        return None


def score_spec(obj) -> tuple:
    """(점수 0~4, 메모)"""
    if obj is None:
        return 0, "JSON 파싱 실패"
    notes = []
    s = 0
    if all(k in obj for k in REQUIRED_KEYS):
        s += 2
    else:
        notes.append("필수필드 누락")
    if obj.get("diagram_type") in VALID_TYPES:
        s += 1
    else:
        notes.append("유형값 이상")
    if isinstance(obj.get("nodes"), list) and len(obj.get("nodes", [])) >= 3:
        s += 1
    else:
        notes.append("노드부족")
    return s, (", ".join(notes) or "정상")


def run_model(client, label, model_id):
    t0 = time.time()
    try:
        kwargs = dict(
            model=model_id,
            messages=[{"role": "system", "content": SYSTEM},
                      {"role": "user", "content": TASK}],
            temperature=0.3, top_p=0.9, max_tokens=2048, stream=False,
        )
        if label.startswith("deepseek"):
            kwargs["extra_body"] = {"chat_template_kwargs": {"thinking": False}}
        resp = client.chat.completions.create(**kwargs)
        text = resp.choices[0].message.content or ""
        dt = time.time() - t0
        obj = extract_json(text)
        sc, note = score_spec(obj)
        cjk = "한자오염!" if has_cjk(text) else "깨끗"
        n_nodes = len(obj.get("nodes", [])) if obj else 0
        return dict(label=label, ok=True, sec=round(dt, 1), score=sc,
                    cjk=cjk, nodes=n_nodes, note=note,
                    dtype=(obj or {}).get("diagram_type", "-"))
    except Exception as e:
        dt = time.time() - t0
        msg = str(e)
        short = "404 모델없음" if "404" in msg else ("429 한도" if "429" in msg else msg[:60])
        return dict(label=label, ok=False, sec=round(dt, 1), score=0,
                    cjk="-", nodes=0, note=short, dtype="-")


def main():
    key = find_key()
    if not key or not key.startswith("nvapi-"):
        print("[중지] NVIDIA 키가 없습니다. 환경변수 NVIDIA_API_KEY에 nvapi-... 키를 넣고 다시 실행하세요.")
        return
    client = OpenAI(base_url=BASE_URL, api_key=key)

    print("=" * 78)
    print(" 도식화 챗봇 — 무료 모델 실측 비교 (같은 과제, JSON 스펙 산출)")
    print("=" * 78)
    header = f"{'모델':<18}{'성공':<5}{'점수/4':<7}{'초':<7}{'노드':<5}{'유형':<12}{'한자':<9}메모"
    print(header)
    print("-" * 78)

    results = []
    for label, mid in MODELS.items():
        r = run_model(client, label, mid)
        results.append(r)
        print(f"{r['label']:<18}{('O' if r['ok'] else 'X'):<5}"
              f"{r['score']:<7}{r['sec']:<7}{r['nodes']:<5}"
              f"{r['dtype']:<12}{r['cjk']:<9}{r['note']}")
        time.sleep(2.0)  # 분당 40회 제한 보호

    print("-" * 78)
    ranked = sorted([r for r in results if r["ok"]],
                    key=lambda r: (-r["score"], r["sec"]))
    if ranked:
        best = ranked[0]
        print(f"\n▶ 추천(점수 높고 빠른 순 1위): {best['label']}  "
              f"(점수 {best['score']}/4, {best['sec']}초, 한자 {best['cjk']})")
        print("  * 점수가 같으면 더 빠른 모델이 위로 온다. 여러 번 돌려 일관성도 확인하라.")
    else:
        print("모든 모델이 실패했다. 모델 이름(404) 또는 키 권한(401/403)을 확인하라.")


if __name__ == "__main__":
    main()
