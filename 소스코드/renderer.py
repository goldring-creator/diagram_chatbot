# -*- coding: utf-8 -*-
"""
renderer.py — 도식 설계도(JSON) → 무채색 학술 SVG
설계문서 3·4를 코드화: 집안 스타일을 상수로 고정하고,
svg-academic-diagram 스킬의 좌표 공식과 대칭 검증을 그대로 이식한다.
감각이 아니라 공식으로 배치하고, 추정이 아니라 계산으로 검증한다.
AI는 이 파일을 호출하지 않는다(그림은 100% 파이썬이 그린다).
"""

import re
import math
import html

# ══════════════════ 집안 스타일(house style) 상수 — 한 곳에서 고정 ══════════════════
FONT = "'Apple SD Gothic Neo','AppleGothic','Malgun Gothic','맑은 고딕',sans-serif"

PALETTE = {
    "bg":        "#ffffff",
    "emph_fill": "#333333",   # 강조 박스(어두움)
    "emph_text": "#ffffff",   # 강조 박스 글씨(흰색)
    "norm_fill": "#f2f2f2",   # 일반 박스
    "norm_fill2": "#e9e9e9",  # 일반 박스(짝수/대안)
    "norm_text": "#222222",
    "ghost_fill": "#fafafa",  # 흐린 박스
    "ghost_text": "#999999",
    "border":    "#555555",
    "border_lt": "#888888",
    "border_xlt": "#dddddd",
    "dim":       "#777777",   # 흐린 텍스트(부제)
    "dim2":      "#999999",
    "arrow":     "#555555",
}

# 크기 규격
NODE_W, NODE_H = 150, 46          # 일반 노드
ROOT_W, ROOT_H = 168, 52          # 강조/루트 노드
H_GAP, V_GAP = 34, 62             # 노드 간 수평·수직 간격
MARGIN = 34                       # 캔버스 여백
TITLE_H = 34                      # 상단 제목 영역
CAPTION_H = 26                    # 하단 각주 영역

FS_TITLE = 17                     # 제목
FS_LABEL = 14                     # 노드 라벨
FS_SUB = 11                       # 부제
FS_EDGE = 11                      # 엣지 라벨
FS_CAPTION = 10                   # 각주


# ══════════════════ 문자열·측정 헬퍼 ══════════════════
def esc(s) -> str:
    return html.escape(str(s if s is not None else ""), quote=True)


def text_w(s: str, fs: float) -> float:
    """텍스트 픽셀 폭 추정(한글=전각 1.0, 그 외 0.56). 박스 자동 폭 계산용."""
    w = 0.0
    for ch in str(s):
        w += fs * (1.0 if ord(ch) > 0x1100 else 0.56)
    return w


# ══════════════════ SVG 조각 ══════════════════
def _defs() -> str:
    a = PALETTE["arrow"]
    return f'''  <defs>
    <marker id="aw" markerWidth="9" markerHeight="9" refX="7.5" refY="3"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L8,3 L0,6 Z" fill="{a}"/>
    </marker>
    <marker id="awd" markerWidth="9" markerHeight="9" refX="7.5" refY="3"
            orient="auto" markerUnits="userSpaceOnUse">
      <path d="M0,0 L8,3 L0,6 Z" fill="{PALETTE['border_lt']}"/>
    </marker>
  </defs>
'''


def _svg_open(w, h) -> str:
    return (f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {w:.0f} {h:.0f}" '
            f'width="{w:.0f}" height="{h:.0f}" font-family="{FONT}">\n'
            f'  <rect x="0" y="0" width="{w:.0f}" height="{h:.0f}" fill="{PALETTE["bg"]}"/>\n')


def _title(w, title) -> str:
    if not title:
        return ""
    return (f'  <text x="{w/2:.1f}" y="{TITLE_H-12}" text-anchor="middle" '
            f'font-size="{FS_TITLE}" font-weight="bold" fill="{PALETTE["norm_text"]}">'
            f'{esc(title)}</text>\n')


def _caption(w, h, caption) -> str:
    if not caption:
        return ""
    return (f'  <text x="{MARGIN}" y="{h-9:.1f}" text-anchor="start" '
            f'font-size="{FS_CAPTION}" fill="{PALETTE["dim"]}">※ {esc(caption)}</text>\n')


def _wrap_label(label, box_w):
    """박스폭(box_w)에 맞춰 라벨을 최대 2줄로 접는다.
    공백이 있으면 단어 단위, 없으면(한글 라벨 다수) 글자 단위로 접는다."""
    s = str(label)
    avail = max(box_w - 16, FS_LABEL * 2)
    if text_w(s, FS_LABEL) <= avail:
        return [s]
    if " " in s:
        words = s.split(" ")
        l1 = [words.pop(0)]
        while words and text_w(" ".join(l1 + [words[0]]), FS_LABEL) <= avail:
            l1.append(words.pop(0))
        return [" ".join(l1), " ".join(words)] if words else [" ".join(l1)]
    cut = 1
    for i in range(2, len(s)):
        if text_w(s[:i], FS_LABEL) > avail:
            break
        cut = i
    return [s[:cut], s[cut:]]


def draw_box(cx, cy, w, h, label, sub, role) -> str:
    """중심(cx,cy) 기준 노드 박스 하나. role: emphasis|normal|ghost."""
    x, y = cx - w / 2, cy - h / 2
    if role == "emphasis":
        fill, txt, stroke, dash, rx = (PALETTE["emph_fill"], PALETTE["emph_text"],
                                       PALETTE["emph_fill"], "", 10)
    elif role == "ghost":
        fill, txt, stroke, dash, rx = (PALETTE["ghost_fill"], PALETTE["ghost_text"],
                                       PALETTE["border_lt"], ' stroke-dasharray="4,3"', 8)
    else:
        fill, txt, stroke, dash, rx = (PALETTE["norm_fill"], PALETTE["norm_text"],
                                       PALETTE["border"], "", 8)
    sub_txt = PALETTE["emph_text"] if role == "emphasis" else PALETTE["dim"]
    out = [f'  <rect x="{x:.1f}" y="{y:.1f}" width="{w:.1f}" height="{h:.1f}" rx="{rx}" '
           f'fill="{fill}" stroke="{stroke}" stroke-width="1.4"{dash}/>']
    lines = _wrap_label(label, w)
    if sub:
        base = cy - (len(lines) - 1) * (FS_LABEL * 0.62) - 3
        for i, ln in enumerate(lines):
            out.append(f'  <text x="{cx:.1f}" y="{base + i*FS_LABEL*1.15:.1f}" '
                       f'text-anchor="middle" font-size="{FS_LABEL}" font-weight="bold" '
                       f'fill="{txt}">{esc(ln)}</text>')
        out.append(f'  <text x="{cx:.1f}" y="{cy + h/2 - 8:.1f}" text-anchor="middle" '
                   f'font-size="{FS_SUB}" fill="{sub_txt}">{esc(sub)}</text>')
    else:
        base = cy - (len(lines) - 1) * (FS_LABEL * 0.62) + FS_LABEL * 0.36
        for i, ln in enumerate(lines):
            out.append(f'  <text x="{cx:.1f}" y="{base + i*FS_LABEL*1.15:.1f}" '
                       f'text-anchor="middle" font-size="{FS_LABEL}" font-weight="bold" '
                       f'fill="{txt}">{esc(ln)}</text>')
    return "\n".join(out) + "\n"


def draw_ellipse(cx, cy, rx, ry, label, sub, role="normal") -> str:
    """SEM 잠재변수용 타원 (흰 배경 + 진한 테두리, 강조 시 어두운 채움)."""
    if role == "emphasis":
        fill, txt, sub_txt = PALETTE["emph_fill"], PALETTE["emph_text"], PALETTE["emph_text"]
    else:
        fill, txt, sub_txt = PALETTE["bg"], PALETTE["norm_text"], PALETTE["dim"]
    out = [f'  <ellipse cx="{cx:.1f}" cy="{cy:.1f}" rx="{rx:.1f}" ry="{ry:.1f}" '
           f'fill="{fill}" stroke="{PALETTE["border"]}" stroke-width="1.6"/>']
    base = cy + FS_LABEL * 0.36 - (7 if sub else 0)
    out.append(f'  <text x="{cx:.1f}" y="{base:.1f}" text-anchor="middle" '
               f'font-size="{FS_LABEL}" font-weight="bold" fill="{txt}">{esc(label)}</text>')
    if sub:
        out.append(f'  <text x="{cx:.1f}" y="{base + FS_SUB * 1.35:.1f}" text-anchor="middle" '
                   f'font-size="{FS_SUB}" fill="{sub_txt}">{esc(sub)}</text>')
    return "\n".join(out) + "\n"


def _edge_line(x1, y1, x2, y2, style, label=None) -> str:
    if style == "measure":                     # 잠재변수→관측지표 (가는 실선)
        dash, mk, sw, col = "", "url(#awd)", 1.0, PALETTE["border_lt"]
    elif style == "dashed":
        dash, mk, sw, col = ' stroke-dasharray="5,4"', "url(#awd)", 1.2, PALETTE["border_lt"]
    else:
        dash, mk, sw, col = "", "url(#aw)", 1.7, PALETTE["arrow"]
    out = (f'  <line x1="{x1:.1f}" y1="{y1:.1f}" x2="{x2:.1f}" y2="{y2:.1f}" '
           f'stroke="{col}" stroke-width="{sw}"{dash} marker-end="{mk}"/>\n')
    if label:
        mx, my = (x1 + x2) / 2, (y1 + y2) / 2
        out += (f'  <rect x="{mx-text_w(label,FS_EDGE)/2-3:.1f}" y="{my-9:.1f}" '
                f'width="{text_w(label,FS_EDGE)+6:.1f}" height="15" fill="{PALETTE["bg"]}"/>\n')
        out += (f'  <text x="{mx:.1f}" y="{my+3:.1f}" text-anchor="middle" '
                f'font-size="{FS_EDGE}" fill="{PALETTE["dim"]}">{esc(label)}</text>\n')
    return out


# ══════════════════ 공통: 노드/엣지 인덱싱 ══════════════════
def _index(spec):
    nodes = {n["id"]: n for n in spec.get("nodes", []) if n.get("id")}
    edges = [e for e in spec.get("edges", []) if e.get("from") in nodes and e.get("to") in nodes]
    return nodes, edges


def _roots(nodes, edges):
    targets = {e["to"] for e in edges}
    roots = [nid for nid in nodes if nid not in targets]
    return roots or list(nodes)[:1]


def _edge_index(spec, e) -> int:
    """spec["edges"] 원본 리스트에서의 인덱스 (클릭 편집용 식별자)."""
    try:
        return spec.get("edges", []).index(e)
    except ValueError:
        return -1


def _offset_of(spec, nid):
    """사용자가 드래그로 옮긴 노드의 이동량 (spec["offsets"] = {id: [dx, dy]})."""
    v = (spec.get("offsets") or {}).get(nid)
    if isinstance(v, (list, tuple)) and len(v) == 2:
        try:
            return float(v[0]), float(v[1])
        except (TypeError, ValueError):
            return 0.0, 0.0
    return 0.0, 0.0


# ══════════════════ A. 트리 (tidy tree, 수직) ══════════════════
def render_tree(spec) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요."), [], []
    children = {}
    for e in edges:
        children.setdefault(e["from"], []).append(e["to"])
    roots = _roots(nodes, edges)

    pos = {}                       # id -> (cx, cy, depth)
    slot = [0]
    seen = set()

    def layout(nid, depth):
        if nid in seen:            # 순환 방지
            return
        seen.add(nid)
        kids = children.get(nid, [])
        real_kids = [k for k in kids if k not in pos and k != nid]
        for k in real_kids:
            layout(k, depth + 1)
        placed = [k for k in kids if k in pos]
        if placed:
            cx = sum(pos[k][0] for k in placed) / len(placed)
        else:
            cx = MARGIN + slot[0] * (NODE_W + H_GAP) + NODE_W / 2
            slot[0] += 1
        pos[nid] = (cx, 0, depth)

    for r in roots:
        layout(r, 0)
    for nid in nodes:              # 고아 노드도 배치
        if nid not in pos:
            layout(nid, 0)

    maxdepth = max(d for _, _, d in pos.values())
    for nid, (cx, _, d) in list(pos.items()):
        cy = TITLE_H + MARGIN + d * (NODE_H + V_GAP) + NODE_H / 2
        pos[nid] = (cx, cy, d)

    # 사용자 드래그 오프셋 적용 (해당 노드는 대칭 검증 제외)
    offset_ids = set()
    for nid in list(pos):
        dx, dy = _offset_of(spec, nid)
        if dx or dy:
            offset_ids.add(nid)
            cx, cy, d = pos[nid]
            pos[nid] = (max(NODE_W / 2 + 8, cx + dx),
                        max(TITLE_H + NODE_H / 2 + 8, cy + dy), d)

    width = MARGIN + slot[0] * (NODE_W + H_GAP) - H_GAP + MARGIN
    width = max(width, 640)
    height = TITLE_H + MARGIN + (maxdepth + 1) * (NODE_H + V_GAP) - V_GAP + MARGIN + CAPTION_H
    if offset_ids:                 # 옮긴 노드가 캔버스 밖으로 나가지 않게 확장
        width = max(width, max(x for x, _, _ in pos.values()) + NODE_W / 2 + MARGIN)
        height = max(height, max(y for _, y, _ in pos.values()) + NODE_H / 2 + MARGIN + CAPTION_H)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    ehits = []
    for e in edges:
        x1, y1, _ = pos[e["from"]]
        x2, y2, _ = pos[e["to"]]
        body.append(_edge_line(x1, y1 + NODE_H / 2, x2, y2 - NODE_H / 2 - 4,
                               e.get("style", "solid"), e.get("label")))
        ehits.append({"ei": _edge_index(spec, e), "x1": x1, "y1": y1 + NODE_H / 2,
                      "x2": x2, "y2": y2 - NODE_H / 2 - 4})
    hits = []
    for nid, n in nodes.items():
        cx, cy, d = pos[nid]
        role = n.get("role") or ("emphasis" if d == 0 else "normal")
        body.append(draw_box(cx, cy, NODE_W, NODE_H, n.get("label", nid), n.get("sub"), role))
        hits.append({"id": nid, "x": cx - NODE_W / 2, "y": cy - NODE_H / 2,
                     "w": NODE_W, "h": NODE_H})
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")

    # 대칭 검증: 각 부모 cx == 자식들 cx 중점 (드래그로 옮긴 노드는 제외)
    for pid, kids in children.items():
        placed = [k for k in kids if k in pos and k not in offset_ids]
        if pid in pos and pid not in offset_ids and placed and len(placed) == len(
                [k for k in kids if k in pos]):
            mid = sum(pos[k][0] for k in placed) / len(placed)
            # assert문은 python -O 실행 시 제거되므로 명시적으로 검사한다
            if abs(pos[pid][0] - mid) >= 0.5:
                raise AssertionError(f"트리 대칭 위반: {pid}")
    return "".join(body), hits, ehits


# ══════════════════ B. 플로우차트 (주경로 체인 + 오른쪽 분기) ══════════════════
def render_flowchart(spec) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요."), [], []
    order = [n["id"] for n in spec.get("nodes", []) if n.get("id") in nodes]
    outdeg = {}
    for e in edges:
        outdeg.setdefault(e["from"], []).append(e)

    def is_cond(nid):
        return len(outdeg.get(nid, [])) >= 2

    # 주경로(main): 시작 노드에서 '첫 번째 나가는 엣지'를 따라 내려가는 척추
    start = next((nid for nid in order if nodes[nid].get("role") == "emphasis"), None)
    start = start or (order[0] if order else None)
    main, seen, cur = [], set(), start
    while cur and cur not in seen:
        main.append(cur); seen.add(cur)
        outs = outdeg.get(cur, [])
        cur = outs[0]["to"] if outs else None
    side = [nid for nid in order if nid not in seen]     # 분기로만 닿는 노드 → 오른쪽

    # 열 좌표
    main_cx = MARGIN + ROOT_W / 2
    side_cx = main_cx + ROOT_W / 2 + 150
    route_x = main_cx + ROOT_W / 2 + 70                   # 분기 꺾임 세로선 위치
    has_side = bool(side)
    width = max(560, (side_cx + NODE_W / 2 + MARGIN) if has_side else (main_cx + ROOT_W / 2 + MARGIN))

    # 세로 배치
    pos, kind = {}, {}
    row_h = ROOT_H + V_GAP
    y = TITLE_H + MARGIN + ROOT_H / 2
    row_of = {}
    for i, nid in enumerate(main):
        pos[nid] = (main_cx, y); row_of[nid] = y
        kind[nid] = "cond" if is_cond(nid) else ("emph" if nodes[nid].get("role") == "emphasis" else "proc")
        y += row_h
    bottom = y
    # side 노드: 자신을 가리키는 분기 소스의 행에 맞춰 오른쪽에 배치
    for snid in side:
        src = next((e["from"] for e in edges if e["to"] == snid and e["from"] in row_of), None)
        sy = row_of.get(src, bottom)
        while any(abs(sy - vy) < 4 and vx == side_cx for vx, vy in pos.values()):
            sy += row_h
        pos[snid] = (side_cx, sy); row_of[snid] = sy
        kind[snid] = "cond" if is_cond(snid) else ("emph" if nodes[snid].get("role") == "emphasis" else "proc")
        bottom = max(bottom, sy + ROOT_H / 2 + V_GAP)
    height = bottom - V_GAP + MARGIN + CAPTION_H

    def half_h(nid):
        return 34 if kind[nid] == "cond" else ROOT_H / 2

    def half_w(nid):
        if kind[nid] == "cond":
            return max(70, text_w(nodes[nid].get("label", nid), FS_LABEL) / 2 + 20)
        return ROOT_W / 2 if kind[nid] == "emph" else NODE_W / 2

    # 사용자 드래그 오프셋 적용 + 캔버스 확장
    offset_any = False
    for nid in list(pos):
        dx, dy = _offset_of(spec, nid)
        if dx or dy:
            offset_any = True
            x, y = pos[nid]
            pos[nid] = (max(half_w(nid) + 8, x + dx), max(TITLE_H + half_h(nid) + 8, y + dy))
    if offset_any:
        width = max(width, max(pos[n][0] + half_w(n) for n in pos) + MARGIN)
        height = max(height, max(pos[n][1] + half_h(n) for n in pos) + MARGIN + CAPTION_H)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    main_set = set(main)
    # 엣지
    ehits = []
    for e in edges:
        a, b = e["from"], e["to"]
        xa, ya = pos[a]; xb, yb = pos[b]
        primary = outdeg.get(a) and outdeg[a][0] is e
        if primary and b in main_set and yb > ya:        # 척추 직선(아래로)
            body.append(_edge_line(xa, ya + half_h(a), xb, yb - half_h(b) - 4,
                                   e.get("style", "solid"), e.get("label")))
            ehits.append({"ei": _edge_index(spec, e), "x1": xa, "y1": ya + half_h(a),
                          "x2": xb, "y2": yb - half_h(b) - 4})
        else:                                            # 오른쪽으로 꺾는 분기/우회
            sx = xa + half_w(a)
            # route_x가 대상 왼쪽이면 대상 왼쪽 가장자리에, 오른쪽이면 오른쪽 가장자리에 화살표
            tx = (xb - half_w(b) - 2) if route_x <= xb else (xb + half_w(b) + 2)
            body.append(f'  <path d="M {sx:.1f} {ya:.1f} H {route_x:.1f} V {yb:.1f} '
                        f'H {tx:.1f}" fill="none" stroke="{PALETTE["arrow"]}" '
                        f'stroke-width="1.6" marker-end="url(#aw)"/>\n')
            if abs(ya - yb) < 4:                         # 수평 분기 → 그 선분
                ehits.append({"ei": _edge_index(spec, e), "x1": sx, "y1": ya, "x2": tx, "y2": yb})
            else:                                        # ㄱ자 분기 → 세로 구간이 클릭 대상
                ehits.append({"ei": _edge_index(spec, e), "x1": route_x, "y1": ya,
                              "x2": route_x, "y2": yb})
            if e.get("label"):
                ly = ya - 7 if abs(ya - yb) < 4 else (ya + yb) / 2
                body.append(f'  <text x="{route_x+5:.1f}" y="{ly:.1f}" text-anchor="start" '
                            f'font-size="{FS_EDGE}" fill="{PALETTE["dim"]}">{esc(e["label"])}</text>\n')
    # 노드
    hits = []
    for nid in pos:
        n = nodes[nid]; x, yy = pos[nid]
        if kind[nid] == "cond":
            body.append(_diamond(x, yy, n.get("label", nid)))
        elif kind[nid] == "emph":
            body.append(draw_box(x, yy, ROOT_W, ROOT_H, n.get("label", nid), n.get("sub"), "emphasis"))
        else:
            body.append(draw_box(x, yy, NODE_W, ROOT_H, n.get("label", nid), n.get("sub"), "normal"))
        hits.append({"id": nid, "x": x - half_w(nid), "y": yy - half_h(nid),
                     "w": half_w(nid) * 2, "h": half_h(nid) * 2})
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body), hits, ehits


def _diamond(cx, cy, label) -> str:
    hw, hh = max(70, text_w(label, FS_LABEL) / 2 + 20), 34
    pts = f"{cx},{cy-hh} {cx+hw},{cy} {cx},{cy+hh} {cx-hw},{cy}"
    return (f'  <polygon points="{pts}" fill="{PALETTE["norm_fill2"]}" '
            f'stroke="{PALETTE["border"]}" stroke-width="1.4"/>\n'
            f'  <text x="{cx:.1f}" y="{cy+4:.1f}" text-anchor="middle" '
            f'font-size="{FS_LABEL}" fill="{PALETTE["norm_text"]}">{esc(label)}</text>\n')


# ══════════════════ 공통 레이어드 배치 (수평 DAG) ══════════════════
def _layers(nodes, edges):
    """각 노드의 레이어 = 루트로부터의 최장 경로 길이."""
    children = {}
    indeg = {nid: 0 for nid in nodes}
    for e in edges:
        children.setdefault(e["from"], []).append(e["to"])
        indeg[e["to"]] = indeg.get(e["to"], 0) + 1
    layer = {nid: 0 for nid in nodes}
    # 위상 순서로 최장경로 완화
    from collections import deque
    q = deque([n for n in nodes if indeg[n] == 0] or list(nodes)[:1])
    seen = set()
    order = []
    ind = dict(indeg)
    while q:
        u = q.popleft()
        if u in seen:
            continue
        seen.add(u); order.append(u)
        for v in children.get(u, []):
            layer[v] = max(layer[v], layer[u] + 1)
            ind[v] -= 1
            if ind[v] <= 0:
                q.append(v)
    for nid in nodes:              # 미방문 노드 보정
        if nid not in seen:
            order.append(nid)
    return layer, order


def render_path_model(spec):
    """경로모형. 관측지표(kind:"observed" 또는 style:"measure" 엣지)가 있으면
    SEM 표기(잠재변수=타원, 지표=상단 작은 사각)로, 없으면 기존 수평 배치로 그린다."""
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요."), [], []
    measure = [e for e in edges
               if e.get("style") == "measure" or nodes[e["to"]].get("kind") == "observed"]
    observed = ({e["to"] for e in measure}
                | {nid for nid in nodes if nodes[nid].get("kind") == "observed"})
    if not observed:
        return _render_horizontal(spec, emphasize_last=True)
    return _render_sem(spec, nodes, edges, observed, measure)


IND_W, IND_H = 118, 44                 # SEM 관측지표 박스


def _render_sem(spec, nodes, edges, observed, measure) -> tuple:
    main = [nid for nid in nodes if nid not in observed]
    if not main:
        return _fallback(spec, "잠재/구조 변수가 없습니다 — 구조 경로를 적어 주세요."), [], []
    struct = [e for e in edges
              if e not in measure and e["from"] not in observed and e["to"] not in observed]
    mnodes = {nid: nodes[nid] for nid in main}
    layer, order = _layers(mnodes, struct)
    maxlayer = max(layer.values()) if layer else 0
    cols = {}
    for nid in order:
        cols.setdefault(layer[nid], []).append(nid)

    def is_lat(nid):
        return nodes[nid].get("kind") == "latent"

    def half_w(nid):
        if is_lat(nid):
            return max(64.0, text_w(nodes[nid].get("label", ""), FS_LABEL) / 2 + 26)
        return NODE_W / 2

    def half_h(nid):
        return 34.0 if is_lat(nid) else NODE_H / 2

    # 각 잠재변수의 지표 묶음
    ind_of = {}
    for e in measure:
        if e["from"] in mnodes and e["to"] in observed:
            ind_of.setdefault(e["from"], []).append(e["to"])
    band_h = (IND_H + 58) if ind_of else 0     # 지표 밴드 + 측정 화살표 공간

    # 구조(주) 변수 배치 — 수평 레이어
    ROW = 86
    colw = NODE_W + 130
    rows_max = max(len(v) for v in cols.values())
    top_main = TITLE_H + MARGIN + band_h
    col_h = rows_max * ROW
    height = top_main + col_h + MARGIN + CAPTION_H
    canvas_cy = top_main + col_h / 2
    pos = {}
    for L in range(maxlayer + 1):
        ids = cols.get(L, [])
        start_y = canvas_cy - len(ids) * ROW / 2
        cx = MARGIN + 92 + L * colw
        for i, nid in enumerate(ids):
            pos[nid] = (cx, start_y + i * ROW + ROW / 2)
    for nid in list(pos):                      # 드래그 오프셋
        dx, dy = _offset_of(spec, nid)
        if dx or dy:
            x, y = pos[nid]
            pos[nid] = (max(half_w(nid) + 8, x + dx), max(TITLE_H + half_h(nid) + 8, y + dy))

    # 지표 배치 — 상단 밴드에 잠재변수 x 순서대로, 겹치지 않게
    ind_y = TITLE_H + MARGIN + IND_H / 2
    ind_pos = {}
    cur_x = MARGIN + IND_W / 2
    for lat in sorted(ind_of, key=lambda n: pos.get(n, (0, 0))[0]):
        kids = ind_of[lat]
        group_w = len(kids) * IND_W + (len(kids) - 1) * 12
        gx = max(cur_x, pos[lat][0] - group_w / 2 + IND_W / 2)
        for k in kids:
            dx, dy = _offset_of(spec, k)
            ind_pos[k] = (gx + dx, max(TITLE_H + IND_H / 2 + 6, ind_y + dy))
            gx += IND_W + 12
        cur_x = gx + 10
    for k in observed:                          # 측정 엣지 없는 고아 지표도 배치
        if k not in ind_pos:
            ind_pos[k] = (cur_x, ind_y)
            cur_x += IND_W + 12

    width = max([pos[n][0] + half_w(n) for n in pos]
                + [p[0] + IND_W / 2 for p in ind_pos.values()] + [640]) + MARGIN
    height = max(height, max([pos[n][1] + half_h(n) for n in pos]
                             + [p[1] + IND_H / 2 for p in ind_pos.values()])
                 + MARGIN + CAPTION_H)
    for e in struct:                            # 아래로 우회하는 점선 곡선 공간 확보
        if e.get("style") == "dashed" and e["from"] in pos and e["to"] in pos:
            x1, y1 = pos[e["from"]]; x2, y2 = pos[e["to"]]
            if abs(x1 - x2) > colw + 10:
                low = max(y1 + half_h(e["from"]), y2 + half_h(e["to"])) + 50
                height = max(height, low + MARGIN + CAPTION_H)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    ehits = []
    # 측정 화살표 (잠재 위쪽 → 지표 아래쪽)
    for e in measure:
        if e["from"] in pos and e["to"] in ind_pos:
            x1, y1 = pos[e["from"]]
            x2, y2 = ind_pos[e["to"]]
            seg = (x1, y1 - half_h(e["from"]), x2, y2 + IND_H / 2 + 4)
            body.append(_edge_line(*seg, "measure", e.get("label")))
            ehits.append({"ei": _edge_index(spec, e),
                          "x1": seg[0], "y1": seg[1], "x2": seg[2], "y2": seg[3]})
    # 구조 경로 (좌→우, 계수 라벨은 흰 바탕 위에)
    # 점선(직접효과)이 다른 변수를 관통하지 않도록 아래로 우회하는 곡선으로 그린다
    for e in struct:
        a, b = e["from"], e["to"]
        x1, y1 = pos[a]; x2, y2 = pos[b]
        style = e.get("style", "solid")
        if style == "dashed" and abs(x1 - x2) > colw + 10:     # 한 열 이상 건너뛰는 직접효과
            sx, sy = x1 + half_w(a) * 0.5, y1 + half_h(a)
            tx, ty = x2 - half_w(b) * 0.5, y2 + half_h(b) + 5
            mx, my = (sx + tx) / 2, max(sy, ty) + 74
            body.append(f'  <path d="M {sx:.1f} {sy:.1f} Q {mx:.1f} {my:.1f} {tx:.1f} {ty:.1f}" '
                        f'fill="none" stroke="{PALETTE["border_lt"]}" stroke-width="1.2" '
                        f'stroke-dasharray="5,4" marker-end="url(#awd)"/>\n')
            # 곡선의 클릭 판정은 정점 부근 수평 근사 선분으로
            qy = 0.25 * sy + 0.5 * my + 0.25 * ty
            ehits.append({"ei": _edge_index(spec, e), "x1": sx, "y1": qy, "x2": tx, "y2": qy})
            if e.get("label"):
                lx, ly = mx, (max(sy, ty) + my) / 2 + 4        # 곡선 정점 부근
                lw = text_w(e["label"], FS_EDGE)
                body.append(f'  <rect x="{lx-lw/2-3:.1f}" y="{ly-11:.1f}" width="{lw+6:.1f}" '
                            f'height="15" fill="{PALETTE["bg"]}"/>\n')
                body.append(f'  <text x="{lx:.1f}" y="{ly:.1f}" text-anchor="middle" '
                            f'font-size="{FS_EDGE}" fill="{PALETTE["dim"]}">{esc(e["label"])}</text>\n')
        elif abs(x1 - x2) > 4:
            sx = x1 + half_w(a) if x2 > x1 else x1 - half_w(a)
            tx = x2 - half_w(b) - 4 if x2 > x1 else x2 + half_w(b) + 4
            body.append(_edge_line(sx, y1, tx, y2, style, e.get("label")))
            ehits.append({"ei": _edge_index(spec, e), "x1": sx, "y1": y1, "x2": tx, "y2": y2})
        else:
            seg = (x1, y1 + half_h(a), x2, y2 - half_h(b) - 4)
            body.append(_edge_line(*seg, style, e.get("label")))
            ehits.append({"ei": _edge_index(spec, e),
                          "x1": seg[0], "y1": seg[1], "x2": seg[2], "y2": seg[3]})
    # 노드
    hits = []
    for nid in pos:
        n = nodes[nid]
        x, y = pos[nid]
        if is_lat(nid):
            rx, ry = half_w(nid), half_h(nid)
            body.append(draw_ellipse(x, y, rx, ry, n.get("label", nid), n.get("sub"),
                                     n.get("role") or "normal"))
            hits.append({"id": nid, "x": x - rx, "y": y - ry, "w": rx * 2, "h": ry * 2})
        else:
            role = n.get("role") or "normal"
            body.append(draw_box(x, y, NODE_W, NODE_H, n.get("label", nid), n.get("sub"), role))
            hits.append({"id": nid, "x": x - NODE_W / 2, "y": y - NODE_H / 2,
                         "w": NODE_W, "h": NODE_H})
    for nid, (x, y) in ind_pos.items():
        n = nodes[nid]
        body.append(draw_box(x, y, IND_W, IND_H, n.get("label", nid), n.get("sub"), "normal"))
        hits.append({"id": nid, "x": x - IND_W / 2, "y": y - IND_H / 2, "w": IND_W, "h": IND_H})
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body), hits, ehits


def render_framework(spec):
    return _render_horizontal(spec, emphasize_last=False)


def _render_horizontal(spec, emphasize_last) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요."), [], []
    layer, order = _layers(nodes, edges)
    maxlayer = max(layer.values()) if layer else 0
    cols = {}
    for nid in order:
        cols.setdefault(layer[nid], []).append(nid)

    # 노드별 role·폭 먼저 확정 (강조=ROOT_W가 더 넓음 → 폭 잘림 방지)
    role_of, w_of = {}, {}
    for nid in nodes:
        role = nodes[nid].get("role")
        if not role:
            role = "emphasis" if (emphasize_last and layer[nid] == maxlayer) or \
                                 (not emphasize_last and layer[nid] == 0) else "normal"
        role_of[nid] = role
        w_of[nid] = ROOT_W if role == "emphasis" else NODE_W

    colw = NODE_W + 90            # 레이어 간 수평 간격(열 중심 간 거리)
    rows_max = max(len(v) for v in cols.values())
    col_h = rows_max * NODE_H + (rows_max - 1) * (V_GAP - 16)
    height = TITLE_H + MARGIN + col_h + MARGIN + CAPTION_H
    canvas_cy = TITLE_H + MARGIN + col_h / 2

    pos = {}
    for L in range(maxlayer + 1):
        ids = cols.get(L, [])
        n = len(ids)
        total = n * NODE_H + (n - 1) * (V_GAP - 16)
        start_y = canvas_cy - total / 2
        cx = MARGIN + ROOT_W / 2 + L * colw       # 첫 열도 ROOT_W 절반 여백 확보
        for i, nid in enumerate(ids):
            cy = start_y + i * (NODE_H + (V_GAP - 16)) + NODE_H / 2
            pos[nid] = (cx, cy)

    # 사용자 드래그 오프셋 적용
    offset_any = False
    for nid in list(pos):
        dx, dy = _offset_of(spec, nid)
        if dx or dy:
            offset_any = True
            x, y = pos[nid]
            pos[nid] = (max(w_of[nid] / 2 + 8, x + dx), max(TITLE_H + NODE_H / 2 + 8, y + dy))

    # 실제 노드 오른쪽 끝에서 캔버스 폭 역산
    width = max([pos[nid][0] + w_of[nid] / 2 for nid in pos] + [600]) + MARGIN
    if offset_any:
        height = max(height, max(pos[n][1] + NODE_H / 2 for n in pos) + MARGIN + CAPTION_H)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    ehits = []
    for e in edges:
        a, b = e["from"], e["to"]
        x1, y1 = pos[a]; x2, y2 = pos[b]
        if abs(layer[a] - layer[b]) >= 1:                 # 좌→우 가장자리 연결
            seg = (x1 + w_of[a] / 2, y1, x2 - w_of[b] / 2 - 4, y2)
        else:                                             # 같은 레이어(수직 연결)
            seg = (x1, y1 + NODE_H / 2, x2, y2 - NODE_H / 2 - 4)
        body.append(_edge_line(*seg, e.get("style", "solid"), e.get("label")))
        ehits.append({"ei": _edge_index(spec, e),
                      "x1": seg[0], "y1": seg[1], "x2": seg[2], "y2": seg[3]})
    hits = []
    for nid, n in nodes.items():
        cx, cy = pos[nid]
        body.append(draw_box(cx, cy, w_of[nid], NODE_H, n.get("label", nid), n.get("sub"), role_of[nid]))
        hits.append({"id": nid, "x": cx - w_of[nid] / 2, "y": cy - NODE_H / 2,
                     "w": w_of[nid], "h": NODE_H})
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body), hits, ehits


# ══════════════════ C. 레이더 (극좌표 등각) ══════════════════
def render_radar(spec) -> str:
    axes = spec.get("axes", [])
    series = spec.get("series", [])
    n = len(axes)
    if n < 3:
        return _fallback(spec, "레이더는 축(axes)이 3개 이상 필요합니다."), [], []
    width, height = 720, 620
    cx, cy = width / 2, TITLE_H + (height - TITLE_H - CAPTION_H) / 2 + 6
    R = min(width, height - TITLE_H - CAPTION_H) / 2 - 90
    # 값이 비었거나 숫자가 아니어도 전체가 렌더 오류로 죽지 않게 정화한다
    clean_vals = {}
    for si, s in enumerate(series):
        clean_vals[si] = [v if isinstance(v, (int, float)) else 0
                          for v in (s.get("values") or [])]
    maxval = max([max(vs) for vs in clean_vals.values() if vs] + [1])

    def pt(i, r):
        ang = -math.pi / 2 + i * 2 * math.pi / n
        return cx + r * math.cos(ang), cy + r * math.sin(ang)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    # 격자 링
    for g in range(1, 5):
        rr = R * g / 4
        pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in (pt(i, rr) for i in range(n)))
        body.append(f'  <polygon points="{pts}" fill="none" stroke="{PALETTE["border_xlt"]}" '
                    f'stroke-width="1"/>\n')
    # 축선 + 라벨
    for i, ax in enumerate(axes):
        x, y = pt(i, R)
        body.append(f'  <line x1="{cx:.1f}" y1="{cy:.1f}" x2="{x:.1f}" y2="{y:.1f}" '
                    f'stroke="{PALETTE["border_lt"]}" stroke-width="1"/>\n')
        lx, ly = pt(i, R + 26)
        anchor = "middle" if abs(lx - cx) < 6 else ("start" if lx > cx else "end")
        body.append(f'  <text x="{lx:.1f}" y="{ly+4:.1f}" text-anchor="{anchor}" '
                    f'font-size="{FS_SUB+1}" fill="{PALETTE["norm_text"]}">{esc(ax)}</text>\n')
    # 계열(무채색: 진한 회색 → 점선 → 연한 회색)
    grays = ["#333333", "#666666", "#999999", "#bbbbbb"]
    dashes = ["", "6,4", "3,3", "2,3"]
    for si, s in enumerate(series):
        vals = clean_vals[si]
        pts = " ".join(f"{x:.1f},{y:.1f}"
                       for x, y in (pt(i, R * (vals[i] / maxval)) for i in range(min(n, len(vals)))))
        g = grays[si % len(grays)]
        dash = f' stroke-dasharray="{dashes[si % len(dashes)]}"' if dashes[si % len(dashes)] else ""
        body.append(f'  <polygon points="{pts}" fill="{g}" fill-opacity="0.10" '
                    f'stroke="{g}" stroke-width="1.8"{dash}/>\n')
        for i in range(min(n, len(vals))):
            x, y = pt(i, R * (vals[i] / maxval))
            body.append(f'  <circle cx="{x:.1f}" cy="{y:.1f}" r="2.6" fill="{g}"/>\n')
    # 범례
    ly = TITLE_H + 8
    for si, s in enumerate(series):
        g = grays[si % len(grays)]
        body.append(f'  <line x1="{MARGIN}" y1="{ly:.1f}" x2="{MARGIN+22}" y2="{ly:.1f}" '
                    f'stroke="{g}" stroke-width="2.4"/>\n')
        body.append(f'  <text x="{MARGIN+28}" y="{ly+4:.1f}" font-size="{FS_SUB+1}" '
                    f'fill="{PALETTE["norm_text"]}">{esc(s.get("name",""))}</text>\n')
        ly += 20
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body), [], []


# ══════════════════ D. 타임라인 (다중 레인) ══════════════════
def render_timeline(spec) -> str:
    tl = spec.get("timeline", {})
    lanes = tl.get("lanes", [])
    events = tl.get("events", [])
    start, end = tl.get("start"), tl.get("end")
    if not lanes or start is None or end is None or end <= start:
        return _fallback(spec, "타임라인은 start·end·lanes가 필요합니다."), [], []
    width = 960
    lane_h = 96
    left = 150                     # 레인 이름 영역
    x0, x1 = left + 20, width - MARGIN
    top = TITLE_H + MARGIN
    height = top + len(lanes) * lane_h + 40 + CAPTION_H

    def xof(year):
        year = max(start, min(end, year))
        return x0 + (x1 - x0) * (year - start) / (end - start)

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    # 레인 배경 + 이름
    for li, name in enumerate(lanes):
        ly = top + li * lane_h
        fill = PALETTE["norm_fill"] if li % 2 == 0 else "#f8f8f8"
        body.append(f'  <rect x="{MARGIN}" y="{ly:.1f}" width="{width-2*MARGIN:.1f}" '
                    f'height="{lane_h-10:.1f}" fill="{fill}" stroke="{PALETTE["border_xlt"]}"/>\n')
        body.append(f'  <text x="{MARGIN+12}" y="{ly+(lane_h-10)/2+4:.1f}" font-size="{FS_LABEL}" '
                    f'font-weight="bold" fill="{PALETTE["norm_text"]}">{esc(name)}</text>\n')
    # 연도 축
    axis_y = top + len(lanes) * lane_h + 6
    body.append(f'  <line x1="{x0:.1f}" y1="{axis_y:.1f}" x2="{x1:.1f}" y2="{axis_y:.1f}" '
                f'stroke="{PALETTE["border_lt"]}" stroke-width="1.2"/>\n')
    span = end - start
    step = max(1, round(span / 8))
    yr = start
    while yr <= end:
        xx = xof(yr)
        body.append(f'  <line x1="{xx:.1f}" y1="{top:.1f}" x2="{xx:.1f}" y2="{axis_y:.1f}" '
                    f'stroke="{PALETTE["border_xlt"]}" stroke-width="0.8"/>\n')
        body.append(f'  <text x="{xx:.1f}" y="{axis_y+16:.1f}" text-anchor="middle" '
                    f'font-size="{FS_SUB}" fill="{PALETTE["dim"]}">{yr}</text>\n')
        yr += step
    # 같은 레인 사건 연결선
    by_lane = {}
    for ev in events:
        try:
            li = int(ev.get("lane", 0))
        except (TypeError, ValueError):
            li = 0
        li = max(0, min(len(lanes) - 1, li))   # 범위 밖 lane은 클램프(캔버스 밖 유실 방지)
        by_lane.setdefault(li, []).append(ev)
    for li, evs in by_lane.items():
        evs = sorted(evs, key=lambda e: e.get("year", start))
        cyl = top + li * lane_h + (lane_h - 10) / 2
        for a, b in zip(evs, evs[1:]):
            body.append(_edge_line(xof(a.get("year", start)) + 6, cyl,
                                   xof(b.get("year", start)) - 8, cyl, "solid"))
        for ev in evs:
            xx = xof(ev.get("year", start))
            strong = ev.get("weight") == "강"
            r = 7 if strong else 5
            fill = PALETTE["emph_fill"] if strong else PALETTE["norm_fill2"]
            body.append(f'  <circle cx="{xx:.1f}" cy="{cyl:.1f}" r="{r}" fill="{fill}" '
                        f'stroke="{PALETTE["border"]}" stroke-width="1.2"/>\n')
            body.append(f'  <text x="{xx:.1f}" y="{cyl-r-5:.1f}" text-anchor="middle" '
                        f'font-size="{FS_SUB}" fill="{PALETTE["norm_text"]}">{esc(ev.get("label",""))}</text>\n')
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body), [], []


# ══════════════════ 폴백(유형 미상·필드 부족) ══════════════════
def _fallback(spec, msg) -> str:
    width, height = 640, 200
    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title") or "도식")]
    body.append(f'  <text x="{width/2:.1f}" y="{height/2:.1f}" text-anchor="middle" '
                f'font-size="{FS_LABEL}" fill="{PALETTE["dim"]}">{esc(msg)}</text>\n')
    body.append("</svg>\n")
    return "".join(body)


# ══════════════════ 진입점 ══════════════════
RENDERERS = {
    "tree": render_tree,
    "flowchart": render_flowchart,
    "path_model": render_path_model,
    "framework": render_framework,
    "radar": render_radar,
    "timeline": render_timeline,
}


def check_cjk(text: str) -> list:
    """렌더 결과에 한자·가나 오염이 있는지 검사(전역 규칙)."""
    found = []
    for i, ch in enumerate(text):
        code = ord(ch)
        if 0x4E00 <= code <= 0x9FFF or 0x3040 <= code <= 0x30FF:
            found.append(f"'{ch}'(U+{code:04X}) …{text[max(0,i-6):i+6]}…")
    return found


def effective_size_scale(spec: dict) -> float:
    """spec["size_scale"]를 0.5~2.5로 클램프해 반환 (미리보기 좌표 변환에도 사용)."""
    try:
        scale = float(spec.get("size_scale", 1.0))
    except (TypeError, ValueError):
        scale = 1.0
    return max(0.5, min(2.5, scale))


def _apply_size_scale(svg: str, spec: dict) -> str:
    """size_scale을 루트 svg의 width/height에 곱한다.
    viewBox는 그대로라 비율은 유지되고 출력(픽셀) 크기만 커지거나 작아진다."""
    scale = effective_size_scale(spec)
    if abs(scale - 1.0) < 1e-6:
        return svg
    return re.sub(
        r'width="([\d.]+)" height="([\d.]+)"',
        lambda m: f'width="{float(m.group(1)) * scale:.0f}" height="{float(m.group(2)) * scale:.0f}"',
        svg, count=1)


def render(spec: dict):
    """도식 스펙 → (svg_text, warnings, hits, edge_hits).
    hits: 노드·제목·각주 클릭 영역 [{"id","x","y","w","h"}] (viewBox 좌표).
    edge_hits: 화살표 클릭 판정용 선분 [{"ei","x1","y1","x2","y2"}] —
    ei는 spec["edges"] 인덱스. 필수필드 부족·유형미상은 폴백으로 처리."""
    warnings = []
    dtype = spec.get("diagram_type", "")
    fn = RENDERERS.get(dtype)
    if fn is None:
        return _fallback(spec, f"알 수 없는 도식 유형: {dtype}"), [f"유형 미상: {dtype}"], [], []
    try:
        svg, hits, edge_hits = fn(spec)
    except AssertionError as e:
        return _fallback(spec, f"대칭 검증 실패: {e}"), [f"대칭 검증 실패: {e}"], [], []
    except Exception as e:
        return _fallback(spec, f"렌더 오류: {e}"), [f"렌더 오류: {e}"], [], []
    # 제목·각주도 클릭해 수정/삭제할 수 있도록 hit 영역 추가
    m = re.search(r'viewBox="0 0 ([\d.]+) ([\d.]+)"', svg)
    if m:
        vw, vh = float(m.group(1)), float(m.group(2))
        if spec.get("title"):
            tw = text_w(str(spec["title"]), FS_TITLE) + 24
            hits.append({"id": "__title__", "x": vw / 2 - tw / 2, "y": TITLE_H - 32,
                         "w": tw, "h": 30})
        if spec.get("caption"):
            cw = text_w("※ " + str(spec["caption"]), FS_CAPTION) + 12
            hits.append({"id": "__caption__", "x": MARGIN - 4, "y": vh - CAPTION_H + 2,
                         "w": cw, "h": CAPTION_H - 2})
    svg = _apply_size_scale(svg, spec)
    cjk = check_cjk(svg)
    if cjk:
        warnings.append(f"한자/가나 오염 {len(cjk)}건: {cjk[0]}")
    return svg, warnings, hits, edge_hits


# 필수 필드 검증(사용자에게 되묻기용)
def missing_fields(spec: dict) -> list:
    dtype = spec.get("diagram_type")
    miss = []
    if dtype not in RENDERERS:
        miss.append("diagram_type(유형)")
        return miss
    if dtype in ("tree", "flowchart", "path_model", "framework"):
        if not spec.get("nodes"):
            miss.append("nodes(노드)")
    if dtype == "radar" and len(spec.get("axes", [])) < 3:
        miss.append("axes(3개 이상)")
    if dtype == "timeline":
        tl = spec.get("timeline", {})
        if not tl.get("lanes") or tl.get("start") is None or tl.get("end") is None:
            miss.append("timeline(start·end·lanes)")
    return miss
