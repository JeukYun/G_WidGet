"""아이콘 + 바로가기 생성기.

한 번만 실행:  python install.py

결과:
  widget.ico  — 다중 해상도 ICO (16/24/32/48/64/128/256)
  Widget.lnk  — 더블클릭으로 위젯 실행 (콘솔 없음)

이름 변경, 바탕화면/시작메뉴/작업표시줄로 끌어놓기 모두 가능.
"""
from __future__ import annotations

import math
import subprocess
import sys
import tempfile
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).parent.resolve()


def make_sun_icon(size: int = 512) -> Image.Image:
    """둥근 파란 카드 + 흰 햇살. 둥근 캡으로 부드럽게."""
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img, "RGBA")

    radius = int(size * 0.22)
    d.rounded_rectangle((0, 0, size, size), radius, fill=(37, 99, 235, 255))

    cx, cy = size / 2, size / 2
    sun_r     = size * 0.18
    ray_inner = sun_r * 1.55
    ray_outer = sun_r * 2.05
    ray_w     = max(3, int(size * 0.030))
    cap_r     = ray_w / 2

    for i in range(8):
        a = i * math.pi / 4
        x1, y1 = cx + math.cos(a) * ray_inner, cy + math.sin(a) * ray_inner
        x2, y2 = cx + math.cos(a) * ray_outer, cy + math.sin(a) * ray_outer
        d.line([(x1, y1), (x2, y2)], fill=(255, 255, 255, 255), width=ray_w)
        # 둥근 캡
        for px, py in ((x1, y1), (x2, y2)):
            d.ellipse((px - cap_r, py - cap_r, px + cap_r, py + cap_r),
                      fill=(255, 255, 255, 255))

    d.ellipse((cx - sun_r, cy - sun_r, cx + sun_r, cy + sun_r),
              fill=(255, 255, 255, 255))
    return img


def make_ico(path: Path) -> None:
    base = make_sun_icon(512)
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    base.save(path, format="ICO", sizes=sizes)


def make_shortcut(pythonw: Path, script: Path, icon: Path, dest: Path) -> None:
    ps = f"""
$ws = New-Object -ComObject WScript.Shell
$sc = $ws.CreateShortcut('{dest}')
$sc.TargetPath = '{pythonw}'
$sc.Arguments = '"{script}"'
$sc.WorkingDirectory = '{script.parent}'
$sc.IconLocation = '{icon}'
$sc.Description = '날씨 주식 위젯'
$sc.WindowStyle = 7
$sc.Save()
"""
    tmp = Path(tempfile.gettempdir()) / "_make_widget_lnk.ps1"
    tmp.write_text(ps, encoding="utf-8-sig")
    subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(tmp)],
        check=True,
    )


def main():
    icon_path = ROOT / "widget.ico"
    print(f"[1/2] 아이콘 생성 → {icon_path.name}")
    make_ico(icon_path)

    pythonw = Path(sys.executable.replace("python.exe", "pythonw.exe"))
    if not pythonw.exists():
        pythonw = Path(r"C:\Users\yju12\anaconda3\pythonw.exe")
    if not pythonw.exists():
        raise SystemExit(f"pythonw.exe 를 찾을 수 없습니다: {pythonw}")

    # 작업관리자에 'Widget' 으로 표시되도록 pythonw.exe → Widget.exe 복사 후 사용
    widget_exe = pythonw.with_name("Widget.exe")
    if not widget_exe.exists() or widget_exe.stat().st_size != pythonw.stat().st_size:
        import shutil
        shutil.copy2(pythonw, widget_exe)
        print(f"  → {widget_exe.name} 생성")
    pythonw = widget_exe

    script   = ROOT / "widget.py"
    shortcut = ROOT / "Widget.lnk"
    print(f"[2/2] 바로가기 생성 → {shortcut.name}")
    make_shortcut(pythonw, script, icon_path, shortcut)

    print()
    print("완료! 다음부터는 'Widget.lnk' 더블클릭으로 실행하세요.")
    print("바탕화면 · 시작메뉴 · 작업표시줄로 끌어놓기 모두 가능합니다.")
    print(f"이름은 자유롭게 바꿔도 됩니다 (예: '날씨 주식 위젯.lnk').")


if __name__ == "__main__":
    main()
