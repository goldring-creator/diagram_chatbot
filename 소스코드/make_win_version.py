#!/usr/bin/env python3
"""윈도우 .exe 버전 리소스(pyinstaller --version-file)용 파일을 생성한다.

사용: python make_win_version.py <버전> [출력경로]
예:   python make_win_version.py 0.3.6 version_info.txt

CI가 git 태그에서 뽑은 버전을 넣어 호출한다. Korean 문자열이 들어가므로
stdout이 아니라 UTF-8 파일로 직접 기록한다(윈도우 콘솔 인코딩 회피).
"""
import sys


def build(version: str) -> str:
    parts = [int(x) for x in version.split(".")[:3] if x.isdigit()]
    while len(parts) < 3:
        parts.append(0)
    a, b, c = parts[:3]
    return f"""# UTF-8
VSVersionInfo(
  ffi=FixedFileInfo(
    filevers=({a}, {b}, {c}, 0),
    prodvers=({a}, {b}, {c}, 0),
    mask=0x3f,
    flags=0x0,
    OS=0x40004,
    fileType=0x1,
    subtype=0x0,
    date=(0, 0)
  ),
  kids=[
    StringFileInfo([
      StringTable('040904B0', [
        StringStruct('CompanyName', 'goldring'),
        StringStruct('FileDescription', '도식화 챗봇'),
        StringStruct('FileVersion', '{a}.{b}.{c}.0'),
        StringStruct('InternalName', 'DiagramChatbot'),
        StringStruct('OriginalFilename', 'DiagramChatbot.exe'),
        StringStruct('ProductName', 'DiagramChatbot'),
        StringStruct('ProductVersion', '{a}.{b}.{c}.0')
      ])
    ]),
    VarFileInfo([VarStruct('Translation', [1033, 1200])])
  ]
)
"""


def main() -> None:
    version = sys.argv[1] if len(sys.argv) > 1 else "0.0.0"
    out = sys.argv[2] if len(sys.argv) > 2 else "version_info.txt"
    with open(out, "w", encoding="utf-8") as f:
        f.write(build(version))
    print(f"wrote {out} for version {version}")


if __name__ == "__main__":
    main()
