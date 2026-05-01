"""Widget.exe 에 아이콘 + 버전 정보(FileDescription='Widget') 임베드.
작업관리자/Explorer 에 'Widget' 으로 표시되도록 함."""
from __future__ import annotations

import struct
import sys
from pathlib import Path

import win32api

ROOT     = Path(__file__).parent.resolve()
ICO_PATH = ROOT / "widget.ico"

EXE_PATH = Path(sys.executable).with_name("Widget.exe")
if not EXE_PATH.exists():
    EXE_PATH = Path(r"C:\Users\yju12\anaconda3\Widget.exe")

RT_ICON       = 3
RT_GROUP_ICON = 14
RT_VERSION    = 16

LANG_EN_US = 0x0409
CP_UNICODE = 0x04B0


# ─── ICO 파서 / 그룹 아이콘 빌더 ──────────────────────────────────────────────

def parse_ico(data: bytes):
    reserved, type_, count = struct.unpack("<HHH", data[:6])
    if type_ != 1:
        raise ValueError("ICO 형식이 아닙니다")
    entries, images = [], []
    offset = 6
    for _ in range(count):
        w, h, c, _r, planes, bc, size, img_off = struct.unpack(
            "<BBBBHHII", data[offset:offset + 16]
        )
        offset += 16
        images.append(data[img_off:img_off + size])
        entries.append((w, h, c, planes, bc, size))
    return entries, images


def make_group_icon(entries):
    out = struct.pack("<HHH", 0, 1, len(entries))
    for i, (w, h, c, p, bc, size) in enumerate(entries, start=1):
        out += struct.pack("<BBBBHHIH", w, h, c, 0, p, bc, size, i)
    return out


# ─── VS_VERSIONINFO 빌더 ──────────────────────────────────────────────────────

def _pad4(b: bytes) -> bytes:
    while len(b) % 4 != 0:
        b += b"\0\0"
    return b


def _patch_wlength(b: bytes) -> bytes:
    return struct.pack("<H", len(b)) + b[2:]


def _string_entry(key: str, value: str) -> bytes:
    val_bytes = (value + "\0").encode("utf-16-le")
    val_len_chars = len(value) + 1
    key_bytes = (key + "\0").encode("utf-16-le")
    header = struct.pack("<HHH", 0, val_len_chars, 1) + key_bytes
    header = _pad4(header)
    full = _pad4(header + val_bytes)
    return _patch_wlength(full)


def _string_table(lang_cp: str, entries: list) -> bytes:
    strings = b"".join(entries)
    key = (lang_cp + "\0").encode("utf-16-le")
    header = _pad4(struct.pack("<HHH", 0, 0, 1) + key)
    return _patch_wlength(header + strings)


def _string_file_info(lang_cp: str, entries: list) -> bytes:
    table = _string_table(lang_cp, entries)
    key = ("StringFileInfo\0").encode("utf-16-le")
    header = _pad4(struct.pack("<HHH", 0, 0, 1) + key)
    return _patch_wlength(header + table)


def _var_file_info(lang: int, cp: int) -> bytes:
    val = struct.pack("<HH", lang, cp)
    k1 = ("Translation\0").encode("utf-16-le")
    h1 = _pad4(struct.pack("<HHH", 0, 4, 0) + k1)
    var_struct = _patch_wlength(h1 + val)

    k2 = ("VarFileInfo\0").encode("utf-16-le")
    h2 = _pad4(struct.pack("<HHH", 0, 0, 1) + k2)
    return _patch_wlength(h2 + var_struct)


def make_version_info(strings: dict, lang: int = LANG_EN_US, cp: int = CP_UNICODE) -> bytes:
    # VS_FIXEDFILEINFO (52 bytes)
    fixed = struct.pack(
        "<IIIIIIIIIIIII",
        0xFEEF04BD, 0x00010000,
        0, 0, 0, 0,
        0x3F, 0,
        0x00040004,  # VOS_NT_WINDOWS32
        1,           # VFT_APP
        0, 0, 0,
    )

    entries = [_string_entry(k, v) for k, v in strings.items()]
    lang_cp = f"{lang:04X}{cp:04X}"
    sfi = _string_file_info(lang_cp, entries)
    vfi = _var_file_info(lang, cp)

    key = ("VS_VERSION_INFO\0").encode("utf-16-le")
    header = _pad4(struct.pack("<HHH", 0, 52, 0) + key)
    return _patch_wlength(header + fixed + sfi + vfi)


# ─── 메인 ─────────────────────────────────────────────────────────────────────

def main():
    if not ICO_PATH.exists():
        raise SystemExit(f"ICO 없음: {ICO_PATH}")
    if not EXE_PATH.exists():
        raise SystemExit(f"EXE 없음: {EXE_PATH}")

    print(f"[1/4] ICO 파싱: {ICO_PATH.name}")
    entries, images = parse_ico(ICO_PATH.read_bytes())
    grp = make_group_icon(entries)
    print(f"      {len(entries)} 개 사이즈")

    print(f"[2/4] 버전 정보 빌드 (FileDescription='Widget')")
    ver = make_version_info({
        "CompanyName":      "",
        "FileDescription":  "Widget",
        "FileVersion":      "1.0.0.0",
        "InternalName":     "Widget",
        "LegalCopyright":   "",
        "OriginalFilename": "Widget.exe",
        "ProductName":      "Widget",
        "ProductVersion":   "1.0.0.0",
    })

    print(f"[3/4] 리소스 업데이트: {EXE_PATH}")
    # bDeleteExistingResources=True → 기존 리소스 전부 삭제 (Python 아이콘·메타 잔재 제거)
    h = win32api.BeginUpdateResource(str(EXE_PATH), True)
    for i, img in enumerate(images, start=1):
        win32api.UpdateResource(h, RT_ICON, i, img)
    win32api.UpdateResource(h, RT_GROUP_ICON, 1, grp)
    win32api.UpdateResource(h, RT_VERSION,    1, ver, LANG_EN_US)
    win32api.EndUpdateResource(h, False)
    print("[4/4] 완료")


if __name__ == "__main__":
    main()
