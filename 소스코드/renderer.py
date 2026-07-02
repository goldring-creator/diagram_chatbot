# -*- coding: utf-8 -*-
"""
renderer.py — 도식 설계도(JSON) → 무채색 학술 SVG
설계문서 3·4를 코드화: 집안 스타일을 상수로 고정하고,
svg-academic-diagram 스킬의 좌표 공식과 대칭 검증을 그대로 이식한다.
감각이 아니라 공식으로 배치하고, 추정이 아니라 계산으로 검증한다.
AI는 이 파일을 호출하지 않는다(그림은 100% 파이썬이 그린다).
"""

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


def _edge_line(x1, y1, x2, y2, style, label=None) -> str:
    dash = ' stroke-dasharray="5,4"' if style == "dashed" else ""
    mk = "url(#awd)" if style == "dashed" else "url(#aw)"
    sw = 1.2 if style == "dashed" else 1.7
    col = PALETTE["border_lt"] if style == "dashed" else PALETTE["arrow"]
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


# ══════════════════ A. 트리 (tidy tree, 수직) ══════════════════
def render_tree(spec) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요.")
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

    width = MARGIN + slot[0] * (NODE_W + H_GAP) - H_GAP + MARGIN
    width = max(width, 640)
    height = TITLE_H + MARGIN + (maxdepth + 1) * (NODE_H + V_GAP) - V_GAP + MARGIN + CAPTION_H

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    for e in edges:
        x1, y1, _ = pos[e["from"]]
        x2, y2, _ = pos[e["to"]]
        body.append(_edge_line(x1, y1 + NODE_H / 2, x2, y2 - NODE_H / 2 - 4,
                               e.get("style", "solid"), e.get("label")))
    for nid, n in nodes.items():
        cx, cy, d = pos[nid]
        role = n.get("role") or ("emphasis" if d == 0 else "normal")
        body.append(draw_box(cx, cy, NODE_W, NODE_H, n.get("label", nid), n.get("sub"), role))
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")

    # 대칭 검증: 각 부모 cx == 자식들 cx 중점
    for pid, kids in children.items():
        placed = [k for k in kids if k in pos]
        if pid in pos and placed:
            mid = sum(pos[k][0] for k in placed) / len(placed)
            assert abs(pos[pid][0] - mid) < 0.5, f"트리 대칭 위반: {pid}"
    return "".join(body)


# ══════════════════ B. 플로우차트 (주경로 체인 + 오른쪽 분기) ══════════════════
def render_flowchart(spec) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요.")
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

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    main_set = set(main)
    # 엣지
    for e in edges:
        a, b = e["from"], e["to"]
        xa, ya = pos[a]; xb, yb = pos[b]
        primary = outdeg.get(a) and outdeg[a][0] is e
        if primary and b in main_set and yb > ya:        # 척추 직선(아래로)
            body.append(_edge_line(xa, ya + half_h(a), xb, yb - half_h(b) - 4,
                                   e.get("style", "solid"), e.get("label")))
        else:                                            # 오른쪽으로 꺾는 분기/우회
            sx = xa + half_w(a)
            # route_x가 대상 왼쪽이면 대상 왼쪽 가장자리에, 오른쪽이면 오른쪽 가장자리에 화살표
            tx = (xb - half_w(b) - 2) if route_x <= xb else (xb + half_w(b) + 2)
            body.append(f'  <path d="M {sx:.1f} {ya:.1f} H {route_x:.1f} V {yb:.1f} '
                        f'H {tx:.1f}" fill="none" stroke="{PALETTE["arrow"]}" '
                        f'stroke-width="1.6" marker-end="url(#aw)"/>\n')
            if e.get("label"):
                ly = ya - 7 if abs(ya - yb) < 4 else (ya + yb) / 2
                body.append(f'  <text x="{route_x+5:.1f}" y="{ly:.1f}" text-anchor="start" '
                            f'font-size="{FS_EDGE}" fill="{PALETTE["dim"]}">{esc(e["label"])}</text>\n')
    # 노드
    for nid in pos:
        n = nodes[nid]; x, yy = pos[nid]
        if kind[nid] == "cond":
            body.append(_diamond(x, yy, n.get("label", nid)))
        elif kind[nid] == "emph":
            body.append(draw_box(x, yy, ROOT_W, ROOT_H, n.get("label", nid), n.get("sub"), "emphasis"))
        else:
            body.append(draw_box(x, yy, NODE_W, ROOT_H, n.get("label", nid), n.get("sub"), "normal"))
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body)


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
    return _render_horizontal(spec, emphasize_last=True)


def render_framework(spec):
    return _render_horizontal(spec, emphasize_last=False)


def _render_horizontal(spec, emphasize_last) -> str:
    nodes, edges = _index(spec)
    if not nodes:
        return _fallback(spec, "그릴 노드가 없습니다 — 내용을 더 구체적으로 적어 주세요.")
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

    # 실제 노드 오른쪽 끝에서 캔버스 폭 역산
    width = max([pos[nid][0] + w_of[nid] / 2 for nid in pos] + [600]) + MARGIN

    body = [_svg_open(width, height), _defs(), _title(width, spec.get("title"))]
    for e in edges:
        a, b = e["from"], e["to"]
        x1, y1 = pos[a]; x2, y2 = pos[b]
        if abs(layer[a] - layer[b]) >= 1:                 # 좌→우 가장자리 연결
            body.append(_edge_line(x1 + w_of[a] / 2, y1, x2 - w_of[b] / 2 - 4, y2,
                                   e.get("style", "solid"), e.get("label")))
        else:                                             # 같은 레이어(수직 연결)
            body.append(_edge_line(x1, y1 + NODE_H / 2, x2, y2 - NODE_H / 2 - 4,
                                   e.get("style", "solid"), e.get("label")))
    for nid, n in nodes.items():
        cx, cy = pos[nid]
        body.append(draw_box(cx, cy, w_of[nid], NODE_H, n.get("label", nid), n.get("sub"), role_of[nid]))
    body.append(_caption(width, height, spec.get("caption")))
    body.append("</svg>\n")
    return "".join(body)


# ══════════════════ C. 레이더 (극좌표 등각) ══════════════════
def render_radar(spec) -> str:
    axes = spec.get("axes", [])
    series = spec.get("series", [])
    n = len(axes)
    if n < 3:
        return _fallback(spec, "레이더는 축(axes)이 3개 이상 필요합니다.")
    width, height = 720, 620
    cx, cy = width / 2, TITLE_H + (height - TITLE_H - CAPTION_H) / 2 + 6
    R = min(width, height - TITLE_H - CAPTION_H) / 2 - 90
    maxval = max([max(s.get("values", [1])) for s in series] + [1])

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
        vals = s.get("values", [])
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
    return "".join(body)


# ══════════════════ D. 타임라인 (다중 레인) ══════════════════
def render_timeline(spec) -> str:
    tl = spec.get("timeline", {})
    lanes = tl.get("lanes", [])
    events = tl.get("events", [])
    start, end = tl.get("start"), tl.get("end")
    if not lanes or start is None or end is None or end <= start:
        return _fallback(spec, "타임라인은 start·end·lanes가 필요합니다.")
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
            body.append(_edge_line(xof(a["year"]) + 6, cyl, xof(b["year"]) - 8, cyl, "solid"))
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
    return "".join(body)


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


def render(spec: dict):
    """도식 스펙 → (svg_text, warnings). 필수필드 부족·유형미상은 폴백으로 처리."""
    warnings = []
    dtype = spec.get("diagram_type", "")
    fn = RENDERERS.get(dtype)
    if fn is None:
        return _fallback(spec, f"알 수 없는 도식 유형: {dtype}"), [f"유형 미상: {dtype}"]
    try:
        svg = fn(spec)
    except AssertionError as e:
        return _fallback(spec, f"대칭 검증 실패: {e}"), [f"대칭 검증 실패: {e}"]
    except Exception as e:
        return _fallback(spec, f"렌더 오류: {e}"), [f"렌더 오류: {e}"]
    cjk = check_cjk(svg)
    if cjk:
        warnings.append(f"한자/가나 오염 {len(cjk)}건: {cjk[0]}")
    return svg, warnings


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
