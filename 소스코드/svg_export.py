# -*- coding: utf-8 -*-
"""
svg_export.py — SVG 텍스트 저장 + PNG 변환
SVG는 네이티브(텍스트) 저장, PNG는 cairosvg 우선·실패 시 안내.
한글 글꼴이 관건이므로 렌더러가 시스템 글꼴명을 SVG에 명시해 둔다.
"""

import os


def save_svg(svg_text: str, path: str):
    with open(path, "w", encoding="utf-8") as f:
        f.write(svg_text)
    return path


_PNG_OK = None


def png_available() -> bool:
    """cairosvg가 임포트될 뿐 아니라 실제로 렌더(libcairo 로드)까지 되는지 확인한다.
    macOS에서 libcairo가 없으면 임포트는 되지만 렌더가 실패하므로 실제 변환을 1회 시도한다."""
    global _PNG_OK
    if _PNG_OK is not None:
        return _PNG_OK
    try:
        import cairosvg
        cairosvg.svg2png(bytestring=b'<svg xmlns="http://www.w3.org/2000/svg" '
                                     b'width="4" height="4"></svg>')
        _PNG_OK = True
    except Exception:
        _PNG_OK = False
    return _PNG_OK


def svg_to_png(svg_text: str, path: str, scale: float = 2.0):
    """cairosvg로 PNG 저장. 성공하면 path, 실패하면 (None, 오류메시지)."""
    try:
        import cairosvg
    except Exception:
        return None, ("PNG 변환에는 cairosvg가 필요합니다. "
                      "설치: pip install cairosvg  (SVG 저장은 그대로 가능합니다)")
    try:
        cairosvg.svg2png(bytestring=svg_text.encode("utf-8"),
                         write_to=path, scale=scale)
        return path, None
    except Exception as e:
        return None, f"PNG 변환 오류: {e}"


def png_bytes(svg_text: str, scale: float = 1.5):
    """미리보기용 PNG 바이트. (bytes, None) 또는 (None, 오류)."""
    try:
        import cairosvg
    except Exception:
        return None, "cairosvg 미설치"
    try:
        return cairosvg.svg2png(bytestring=svg_text.encode("utf-8"), scale=scale), None
    except Exception as e:
        return None, str(e)


def open_in_browser(svg_text: str, tmp_dir: str):
    """cairosvg가 없을 때 대안: SVG를 임시 HTML로 감싸 브라우저로 연다."""
    import webbrowser
    os.makedirs(tmp_dir, exist_ok=True)
    html_path = os.path.join(tmp_dir, "_preview.html")
    with open(html_path, "w", encoding="utf-8") as f:
        f.write(f'<!DOCTYPE html><html><head><meta charset="utf-8">'
                f'<title>도식 미리보기</title></head>'
                f'<body style="margin:0;background:#f0f0f0;display:flex;'
                f'justify-content:center;padding:20px">{svg_text}</body></html>')
    webbrowser.open("file://" + html_path)
    return html_path
