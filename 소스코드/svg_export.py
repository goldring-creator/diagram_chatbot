# -*- coding: utf-8 -*-
"""
svg_export.py — SVG 텍스트 저장 + PNG 변환
SVG는 네이티브(텍스트) 저장. PNG는 resvg-py(순수 pip 의존성, 배포판 내장) 우선,
cairosvg(시스템 cairo 필요) 폴백. 한글은 시스템 글꼴로 렌더되며
렌더러가 SVG에 '맑은 고딕' 등 글꼴명을 명시해 둔다.
"""

import os
import pathlib


def save_svg(svg_text: str, path: str):
    """(path, None) 또는 (None, 오류메시지)."""
    try:
        with open(path, "w", encoding="utf-8") as f:
            f.write(svg_text)
    except OSError as e:
        return None, f"SVG 저장 오류: {e}"
    return path, None


def _render_png(svg_text: str, scale: float):
    """(png_bytes, None) 또는 (None, 오류메시지). resvg 우선, cairosvg 폴백."""
    try:
        import resvg_py
    except Exception:
        resvg_py = None
    if resvg_py is not None:
        try:
            out = resvg_py.svg_to_bytes(svg_string=svg_text, zoom=float(scale))
            return (out if isinstance(out, bytes) else bytes(out)), None
        except Exception as e:
            return None, f"PNG 변환 오류(resvg): {e}"
    try:
        import cairosvg
    except Exception:
        return None, ("PNG 변환 모듈이 없습니다. 설치: pip install resvg-py "
                      "(배포판 실행파일에는 내장되어 있습니다)")
    try:
        return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), scale=scale), None
    except Exception as e:
        return None, f"PNG 변환 오류: {e}"


_PNG_OK = None


def png_available() -> bool:
    """PNG 변환 백엔드(resvg-py 또는 cairosvg)가 실제로 렌더되는지 1회 확인 후 캐시."""
    global _PNG_OK
    if _PNG_OK is not None:
        return _PNG_OK
    data, _err = _render_png(
        '<svg xmlns="http://www.w3.org/2000/svg" width="4" height="4"></svg>', 1.0)
    _PNG_OK = data is not None
    return _PNG_OK


def svg_to_png(svg_text: str, path: str, scale: float = 2.0):
    """PNG 파일로 저장. 성공하면 (path, None), 실패하면 (None, 오류메시지)."""
    data, err = _render_png(svg_text, scale)
    if err:
        return None, err
    try:
        with open(path, "wb") as f:
            f.write(data)
    except OSError as e:
        return None, f"PNG 저장 오류: {e}"
    return path, None


def png_bytes(svg_text: str, scale: float = 1.5):
    """미리보기용 PNG 바이트. (bytes, None) 또는 (None, 오류)."""
    return _render_png(svg_text, scale)


def open_in_browser(svg_text: str, tmp_dir: str):
    """브라우저로 크게 미리보기: SVG를 임시 HTML로 감싸 연다.
    성공하면 파일 경로, 실패하면 None."""
    import webbrowser
    try:
        os.makedirs(tmp_dir, exist_ok=True)
        html_path = os.path.join(tmp_dir, "_preview.html")
        with open(html_path, "w", encoding="utf-8") as f:
            f.write(f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                    f'<title>도식 미리보기</title></head>'
                    f'<body style="margin:0;background:#f0f0f0;display:flex;'
                    f'justify-content:center;padding:20px">{svg_text}</body></html>')
        # 윈도우 백슬래시·한글 경로는 "file://"+str 조립 시 브라우저가 못 열 수 있다
        webbrowser.open(pathlib.Path(html_path).as_uri())
        return html_path
    except OSError:
        return None
