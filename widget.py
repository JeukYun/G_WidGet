"""날씨 + 주식 데스크탑 위젯 — 투명 글래스 디자인.

Samsung One UI / iOS 위젯 스타일에서 영감.
  - 시스템 백드롭은 끄고 매우 낮은 알파의 반투명 배경을 직접 그려서 벽지가 비침
  - PIL 로 직접 렌더링한 컬러 일러스트 이모지 아이콘
  - 시간별 예보 5칸
  - z-order 맨 아래로 보내 다른 창에 자연스럽게 가려짐
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Optional

from PyQt5.QtCore import (
    QEasingCurve, QEvent, QObject, QPoint, QPropertyAnimation, QRectF,
    QRunnable, Qt, QThreadPool, QTimer, pyqtSignal,
)
from PyQt5.QtGui import (
    QColor, QCursor, QFont, QFontDatabase, QIcon, QLinearGradient,
    QPainter, QPainterPath, QPen, QPixmap, QRadialGradient, QRegion,
)
from PyQt5.QtWidgets import (
    QAction, QApplication, QComboBox, QDialog, QDialogButtonBox, QFormLayout,
    QGridLayout, QHBoxLayout, QInputDialog, QLabel, QLineEdit, QMenu,
    QPushButton, QSizePolicy, QSystemTrayIcon, QVBoxLayout, QWidget,
)

import fetcher
from fetcher import StockData, WeatherData
from icons import emoji_pixmap, desc_to_emoji


# ─── 설정 ─────────────────────────────────────────────────────────────────────

CONFIG_PATH = Path(__file__).parent / "config.json"
LOG_PATH    = Path(__file__).parent / "error.log"

DEFAULTS: dict = {
    "city":          "Seoul",
    "stocks":        ["005930.KS", "AAPL", "TSLA"],
    "unit":          "C",
    "scale":         "M",
    "theme":         "light",
    "pinned":        True,
    "pos_x":         100,
    "pos_y":         100,
    "show_clock":    True,
    "show_stocks":   True,
    "show_cpu":      True,
    "show_ram":      True,
    "show_temp":     True,
    "show_city":     True,
    "show_launcher": True,
    "programs":      [],
    "time_format":   "HH:MM:SS",
}
SCALE_FACTORS = {"S": 0.85, "M": 1.0, "L": 1.2, "XL": 1.45}


def load_config() -> dict:
    if CONFIG_PATH.exists():
        try:
            return {**DEFAULTS, **json.loads(CONFIG_PATH.read_text("utf-8"))}
        except Exception:
            pass
    return dict(DEFAULTS)


def save_config(cfg: dict) -> None:
    CONFIG_PATH.write_text(json.dumps(cfg, indent=2, ensure_ascii=False), "utf-8")


def _log(msg: str) -> None:
    from datetime import datetime
    try:
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write(f"[{datetime.now():%H:%M:%S}] {msg}\n")
    except Exception:
        pass


# ─── 테마 ─────────────────────────────────────────────────────────────────────

LIGHT = {
    "primary":   "#1c1c1e",
    "secondary": "#3a3a3c",   # 더 어둡게 → 라이트 모드 시인성 ↑
    "muted":     "#7a7a82",   # 시스템 정보용 — 톤다운
    "accent":    "#007aff",
    "up":        "#30d158",
    "down":      "#ff453a",
    "divider":   "rgba(60,60,67,30)",
    "tray_bg":   "#f2f2f7",
    "tray_fg":   "#1c1c1e",
}
DARK = {
    "primary":   "#ffffff",
    "secondary": "#cfcfd4",   # 회색 톤 더 밝게 (시인성 ↑)
    "muted":     "#9a9aa2",   # 시스템 정보용 — 더 어둡게 (톤다운)
    "accent":    "#0a84ff",
    "up":        "#30d158",
    "down":      "#ff453a",
    "divider":   "rgba(255,255,255,24)",
    "tray_bg":   "#1c1c1e",
    "tray_fg":   "#ffffff",
}

FONT_STACK = (
    '"Pretendard Variable","Pretendard",'
    '"Noto Sans KR","Noto Sans",'
    '"Segoe UI Variable Display","Segoe UI Variable",'
    '"Segoe UI",sans-serif'
)
PREFERRED_FAMILIES: list = []   # load_bundled_fonts() 가 채워줌


def load_bundled_fonts() -> None:
    """fonts/ 디렉토리의 .ttf/.otf 를 앱 폰트로 등록. 한글 모던 폰트 확보."""
    fonts_dir = Path(__file__).parent / "fonts"
    if not fonts_dir.exists():
        return
    db = QFontDatabase()
    for f in fonts_dir.iterdir():
        if f.suffix.lower() in (".ttf", ".otf"):
            fid = db.addApplicationFont(str(f))
            if fid != -1:
                fams = db.applicationFontFamilies(fid)
                _log(f"폰트 로드: {f.name} → {fams}")
                for fam in fams:
                    if fam not in PREFERRED_FAMILIES:
                        PREFERRED_FAMILIES.insert(0, fam)


def pick_font(size: int, weight: int = QFont.Normal) -> QFont:
    candidates = [
        "Pretendard Variable", "Pretendard",
        "Noto Sans KR", "Noto Sans",
        "Segoe UI Variable Display", "Segoe UI Variable",
        "Segoe UI",
    ]
    db = set(QFontDatabase().families())
    for fam in candidates:
        if fam in db:
            f = QFont(fam, size, weight)
            f.setHintingPreference(QFont.PreferNoHinting)
            return f
    return QFont("Segoe UI", size, weight)


def display_font(size: int, weight: int = QFont.Normal) -> QFont:
    """시계·온도 전용 디스플레이 폰트 — pick_font 통해 Pretendard Variable 확보."""
    f = pick_font(size, weight)
    f.setLetterSpacing(QFont.AbsoluteSpacing, -0.8)
    return f


# ─── 작업표시줄 투명화 ────────────────────────────────────────────────────────

def _trim_memory() -> None:
    """Python GC + Windows Working Set 축소 → 보고되는 RAM 사용량 감소."""
    import gc
    gc.collect()
    gc.collect()  # 두 번 — 순환 참조 정리
    if sys.platform != "win32":
        return
    try:
        import ctypes
        from ctypes import wintypes
        kernel32 = ctypes.windll.kernel32
        h = kernel32.GetCurrentProcess()
        # SIZE_T(-1) 두 개 → 작업 집합 최소로
        SIZE_MAX = ctypes.c_size_t(-1)
        kernel32.SetProcessWorkingSetSize.argtypes = [
            wintypes.HANDLE, ctypes.c_size_t, ctypes.c_size_t
        ]
        kernel32.SetProcessWorkingSetSize.restype = wintypes.BOOL
        kernel32.SetProcessWorkingSetSize(h, SIZE_MAX, SIZE_MAX)
    except Exception as ex:
        _log(f"trim 실패: {ex}")


def _set_taskbar_transparent(enabled: bool) -> None:
    """Shell_TrayWnd + 보조 표시줄(Shell_SecondaryTrayWnd)을 투명/불투명으로 전환.
    SetWindowCompositionAttribute(ACCENT_ENABLE_TRANSPARENTGRADIENT) 방식."""
    if sys.platform != "win32":
        return
    import ctypes
    import ctypes.wintypes as wt

    class _ACCENT(ctypes.Structure):
        _fields_ = [
            ("AccentState",   ctypes.c_uint),
            ("AccentFlags",   ctypes.c_uint),
            ("GradientColor", ctypes.c_uint),
            ("AnimationId",   ctypes.c_uint),
        ]

    class _WCA_DATA(ctypes.Structure):
        _fields_ = [
            ("Attribute",   ctypes.c_uint),
            ("pData",       ctypes.c_void_p),
            ("ulDataSize",  ctypes.c_ulong),
        ]

    ACCENT_DISABLED               = 0
    ACCENT_ENABLE_TRANSPARENTGRAD = 2
    WCA_ACCENT_POLICY             = 19

    user32 = ctypes.windll.user32
    SetWCA = user32.SetWindowCompositionAttribute
    FindW  = user32.FindWindowW

    accent = _ACCENT()
    accent.AccentState   = ACCENT_ENABLE_TRANSPARENTGRAD if enabled else ACCENT_DISABLED
    accent.GradientColor = 0x00000000  # 완전 투명

    data = _WCA_DATA()
    data.Attribute  = WCA_ACCENT_POLICY
    data.pData      = ctypes.cast(ctypes.addressof(accent), ctypes.c_void_p)
    data.ulDataSize = ctypes.sizeof(accent)

    for cls in ("Shell_TrayWnd", "Shell_SecondaryTrayWnd"):
        hwnd = FindW(cls, None)
        while hwnd:
            SetWCA(hwnd, ctypes.byref(data))
            hwnd = user32.FindWindowExW(None, hwnd, cls, None)

    _log(f"작업표시줄 투명: {'ON' if enabled else 'OFF'}")


# ─── 자동 시작 ────────────────────────────────────────────────────────────────

_AUTOSTART_KEY  = r"Software\Microsoft\Windows\CurrentVersion\Run"
_AUTOSTART_NAME = "WeatherStockWidget"


def _set_autostart(enabled: bool) -> None:
    if sys.platform != "win32":
        return
    import winreg
    # 작업관리자에 'Widget' 으로 표시되도록 같은 폴더의 Widget.exe 우선 사용
    exe_path = Path(sys.executable)
    widget_exe = exe_path.with_name("Widget.exe")
    runner = str(widget_exe) if widget_exe.exists() else sys.executable
    cmd = f'"{runner}" "{Path(__file__).resolve()}"'
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0,
                             winreg.KEY_SET_VALUE)
        if enabled:
            winreg.SetValueEx(key, _AUTOSTART_NAME, 0, winreg.REG_SZ, cmd)
        else:
            try:
                winreg.DeleteValue(key, _AUTOSTART_NAME)
            except FileNotFoundError:
                pass
        winreg.CloseKey(key)
        _log(f"자동 시작 {'등록' if enabled else '해제'}")
    except Exception as e:
        _log(f"자동 시작 설정 실패: {e}")


def _get_autostart() -> bool:
    if sys.platform != "win32":
        return False
    import winreg
    try:
        key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, _AUTOSTART_KEY, 0,
                             winreg.KEY_READ)
        winreg.QueryValueEx(key, _AUTOSTART_NAME)
        winreg.CloseKey(key)
        return True
    except Exception:
        return False


# ─── Win32: 둥근 코너 + z-order ───────────────────────────────────────────────

def _apply_glass(hwnd: int, dark: bool) -> bool:
    """Win11 시스템 둥근 코너만 적용. 시스템 백드롭(acrylic)은 꺼서
    배경이 흰색으로 가려지지 않게 함 — 배경은 paintEvent 가 매우 낮은
    알파로 직접 그림."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        from ctypes import c_int, byref, sizeof
        dwm = ctypes.windll.dwmapi

        DWMWA_NCRENDERING_POLICY        = 2
        DWMWA_EXCLUDED_FROM_PEEK        = 12   # Aero Peek / Show Desktop 미리보기 제외
        DWMWA_DISALLOW_PEEK             = 11
        DWMWA_USE_IMMERSIVE_DARK_MODE   = 20
        DWMWA_WINDOW_CORNER_PREFERENCE  = 33
        DWMWA_BORDER_COLOR              = 34
        DWMWA_SYSTEMBACKDROP_TYPE       = 38
        DWMWCP_DONOTROUND               = 1   # DWM 코너 끔 → Qt setMask 로 대체
        DWMSBT_NONE                     = 1   # 시스템 배경 끔
        DWMNCRP_DISABLED                = 1   # NC 렌더링 끔 → 그림자/테두리 제거
        DWMWA_COLOR_NONE                = 0xFFFFFFFE

        # NC 렌더링 완전 비활성 (드롭섀도우·테두리 제거)
        v = c_int(DWMNCRP_DISABLED)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_NCRENDERING_POLICY,
                                   byref(v), sizeof(v))
        # Aero Peek / Show Desktop 미리보기 제외
        v = c_int(1)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_EXCLUDED_FROM_PEEK,
                                   byref(v), sizeof(v))
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_DISALLOW_PEEK,
                                   byref(v), sizeof(v))
        # Win11 1px 하이라이트 제거
        v = c_int(DWMWA_COLOR_NONE)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_BORDER_COLOR,
                                   byref(v), sizeof(v))
        # DWM 둥근 코너 끔 — 코너 처리는 Qt setMask 가 담당
        v = c_int(DWMWCP_DONOTROUND)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_WINDOW_CORNER_PREFERENCE,
                                   byref(v), sizeof(v))
        v = c_int(1 if dark else 0)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_USE_IMMERSIVE_DARK_MODE,
                                   byref(v), sizeof(v))
        v = c_int(DWMSBT_NONE)
        dwm.DwmSetWindowAttribute(hwnd, DWMWA_SYSTEMBACKDROP_TYPE,
                                   byref(v), sizeof(v))
        _log("DWM 투명 모드 적용")
        return True
    except Exception as e:
        _log(f"DWM 설정 예외: {e}")
        return False


def _send_to_bottom(hwnd: int) -> None:
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.SetWindowPos(int(hwnd), 1, 0, 0, 0, 0, 0x0001 | 0x0002 | 0x0010)
    except Exception as e:
        _log(f"send_to_bottom 실패: {e}")


def _pin_to_desktop(hwnd: int) -> bool:
    """위젯을 Progman(바탕화면 창)의 자식으로 부착.
    → Show Desktop / Task View / Win+D 등에 영향받지 않고 진짜 바탕화면 위젯처럼 동작."""
    if sys.platform != "win32":
        return False
    try:
        import ctypes
        user32 = ctypes.windll.user32
        progman = user32.FindWindowW("Progman", None)
        if not progman:
            return False
        # 이미 부착됐으면 skip
        if user32.GetParent(hwnd) == progman:
            return True
        # WorkerW 생성 magic message (Progman에 0x052C 보내면 데스크탑 백드롭 분리됨)
        result = ctypes.c_void_p()
        user32.SendMessageTimeoutW(progman, 0x052C, 0xD, 0, 0, 1000, ctypes.byref(result))
        # SetParent
        old_parent = user32.SetParent(hwnd, progman)
        ok = old_parent != 0
        _log(f"바탕화면(Progman) 자식 부착 {'OK' if ok else '실패'}")
        return ok
    except Exception as ex:
        _log(f"desktop pin 실패: {ex}")
        return False


def _unpin_from_desktop(hwnd: int) -> None:
    """SetParent(NULL)로 다시 top-level로 되돌림."""
    if sys.platform != "win32":
        return
    try:
        import ctypes
        ctypes.windll.user32.SetParent(hwnd, 0)
        _log("바탕화면 부착 해제")
    except Exception as ex:
        _log(f"unpin 실패: {ex}")


# ─── 백그라운드 워커 ──────────────────────────────────────────────────────────

class _Signals(QObject):
    weather_done = pyqtSignal(object)
    stocks_done  = pyqtSignal(object)


class WeatherWorker(QRunnable):
    def __init__(self, city: str, sig: _Signals):
        super().__init__()
        self.city, self.sig = city, sig

    def run(self) -> None:
        try:
            self.sig.weather_done.emit(fetcher.fetch_weather(self.city))
        except Exception as e:
            self.sig.weather_done.emit(e)


class StocksWorker(QRunnable):
    def __init__(self, tickers: list, sig: _Signals):
        super().__init__()
        self.tickers, self.sig = tickers, sig

    def run(self) -> None:
        try:
            self.sig.stocks_done.emit(fetcher.fetch_stocks(self.tickers))
        except Exception as e:
            self.sig.stocks_done.emit(e)


# ─── 설정 다이얼로그 ──────────────────────────────────────────────────────────

class SettingsDialog(QDialog):
    def __init__(self, cfg: dict, theme: dict, parent=None):
        super().__init__(parent)
        self.setWindowTitle("위젯 설정")
        self.setFixedWidth(380)
        is_dark = theme is DARK
        bg, fg = ("#1e2235", theme["primary"]) if is_dark else ("#f8fafc", theme["primary"])
        eb, br = ("#2d3250", "#3d4270") if is_dark else ("#ffffff", "#cbd5e1")
        self.setStyleSheet(
            f"QDialog {{ background:{bg}; color:{fg}; }}"
            f"QLabel  {{ color:{fg}; }}"
            f"QLineEdit, QComboBox {{ background:{eb}; color:{fg};"
            f"  border:1px solid {br}; border-radius:6px; padding:6px; }}"
            "QDialogButtonBox QPushButton {"
            "  background:#1d4ed8; color:#ffffff;"
            "  border:none; border-radius:6px; padding:6px 18px; }"
            "QDialogButtonBox QPushButton:hover { background:#1e40af; }"
        )
        layout = QFormLayout(self)
        layout.setSpacing(12)
        layout.setContentsMargins(20, 20, 20, 20)

        self.city_edit   = QLineEdit(cfg.get("city", "Seoul"))
        self.stocks_edit = QLineEdit(", ".join(cfg.get("stocks", [])))
        self.stocks_edit.setPlaceholderText("예: 005930.KS, AAPL, TSLA")

        self.scale_combo = QComboBox()
        self.scale_combo.addItems(["S (작게)", "M (보통)", "L (크게)", "XL (아주 크게)"])
        self.scale_combo.setCurrentIndex(["S", "M", "L", "XL"].index(cfg.get("scale", "M")))

        self.theme_combo = QComboBox()
        self.theme_combo.addItems(["라이트 (밝은 배경용)", "다크 (어두운 배경용)"])
        self.theme_combo.setCurrentIndex(0 if cfg.get("theme") == "light" else 1)

        self.pin_combo = QComboBox()
        self.pin_combo.addItems(["바탕화면에 고정 (다른 창에 가려짐)", "항상 위에 표시"])
        self.pin_combo.setCurrentIndex(0 if cfg.get("pinned", True) else 1)

        self.clock_combo = QComboBox()
        self.clock_combo.addItems(["표시", "숨김"])
        self.clock_combo.setCurrentIndex(0 if cfg.get("show_clock", True) else 1)

        _fmt_list = ["HH:MM:SS", "HH:MM", "hh:MM:SS AP", "hh:MM AP"]
        _fmt_labels = ["24시간 시:분:초", "24시간 시:분", "12시간 AM/PM 시:분:초", "12시간 AM/PM 시:분"]
        self.timefmt_combo = QComboBox()
        self.timefmt_combo.addItems(_fmt_labels)
        cur_fmt = cfg.get("time_format", "HH:MM:SS")
        self.timefmt_combo.setCurrentIndex(_fmt_list.index(cur_fmt) if cur_fmt in _fmt_list else 0)
        self._fmt_list = _fmt_list

        self.autostart_combo = QComboBox()
        self.autostart_combo.addItems(["켜짐", "꺼짐"])
        self.autostart_combo.setCurrentIndex(0 if _get_autostart() else 1)

        self.stocks_combo = QComboBox()
        self.stocks_combo.addItems(["표시", "숨김"])
        self.stocks_combo.setCurrentIndex(0 if cfg.get("show_stocks", True) else 1)

        self.cpu_combo = QComboBox()
        self.cpu_combo.addItems(["표시", "숨김"])
        self.cpu_combo.setCurrentIndex(0 if cfg.get("show_cpu", True) else 1)

        self.ram_combo = QComboBox()
        self.ram_combo.addItems(["표시", "숨김"])
        self.ram_combo.setCurrentIndex(0 if cfg.get("show_ram", True) else 1)

        self.temp_combo = QComboBox()
        self.temp_combo.addItems(["표시", "숨김"])
        self.temp_combo.setCurrentIndex(0 if cfg.get("show_temp", True) else 1)

        self.launcher_combo = QComboBox()
        self.launcher_combo.addItems(["표시", "숨김"])
        self.launcher_combo.setCurrentIndex(0 if cfg.get("show_launcher", True) else 1)

        self.cityname_combo = QComboBox()
        self.cityname_combo.addItems(["표시", "숨김"])
        self.cityname_combo.setCurrentIndex(0 if cfg.get("show_city", True) else 1)

        layout.addRow("도시:",         self.city_edit)
        layout.addRow("도시명 표시:",   self.cityname_combo)
        layout.addRow("종목:",         self.stocks_edit)
        layout.addRow("주식 패널:",     self.stocks_combo)
        layout.addRow("CPU 사용률:",    self.cpu_combo)
        layout.addRow("RAM 사용량:",    self.ram_combo)
        layout.addRow("CPU 온도:",      self.temp_combo)
        layout.addRow("앱 런처:",       self.launcher_combo)
        layout.addRow("크기:",         self.scale_combo)
        layout.addRow("테마:",         self.theme_combo)
        layout.addRow("표시 위치:",     self.pin_combo)
        layout.addRow("시계:",          self.clock_combo)
        layout.addRow("시간 형식:",     self.timefmt_combo)
        layout.addRow("자동 시작:",     self.autostart_combo)

        hint = QLabel("종목 예: 005930.KS(삼성) · 035720.KS(카카오) · AAPL · MSFT · TSLA")
        hint.setStyleSheet("color:#94a3b8; font-size:10px;")
        layout.addRow(hint)

        btns = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        btns.accepted.connect(self.accept)
        btns.rejected.connect(self.reject)
        layout.addRow(btns)

    def values(self) -> dict:
        tickers = [t.strip().upper() for t in self.stocks_edit.text().split(",") if t.strip()]
        return {
            "city":          self.city_edit.text().strip() or "Seoul",
            "stocks":        tickers,
            "show_stocks":   self.stocks_combo.currentIndex() == 0,
            "show_cpu":      self.cpu_combo.currentIndex() == 0,
            "show_ram":      self.ram_combo.currentIndex() == 0,
            "show_temp":     self.temp_combo.currentIndex() == 0,
            "show_city":     self.cityname_combo.currentIndex() == 0,
            "show_launcher": self.launcher_combo.currentIndex() == 0,
            "scale":         ["S", "M", "L", "XL"][self.scale_combo.currentIndex()],
            "theme":         "light" if self.theme_combo.currentIndex() == 0 else "dark",
            "pinned":        self.pin_combo.currentIndex() == 0,
            "show_clock":    self.clock_combo.currentIndex() == 0,
            "time_format":   self._fmt_list[self.timefmt_combo.currentIndex()],
            "autostart":     self.autostart_combo.currentIndex() == 0,
        }


def _menu_qss(theme: dict) -> str:
    return (
        f"QMenu {{ background:{theme['tray_bg']}; color:{theme['tray_fg']};"
        f"  border:1px solid rgba(200,210,230,80); border-radius:8px; padding:6px; }}"
        f"QMenu::item {{ padding:7px 22px; border-radius:5px; }}"
        f"QMenu::item:selected {{ background:#1d4ed8; color:#ffffff; }}"
    )


# ─── 섹션 위젯들 ──────────────────────────────────────────────────────────────

_KO_WEEKDAY = ["월", "화", "수", "목", "금", "토", "일"]


class ClockSection(QWidget):
    """Apple 스타일 시계 — Pretendard Variable Thin 대형 숫자."""

    _FMT_MAP = {
        "HH:MM:SS":    ("%H", "%M", "%S", False),
        "HH:MM":       ("%H", "%M", "",   False),
        "hh:MM:SS AP": ("%I", "%M", "%S", True),
        "hh:MM AP":    ("%I", "%M", "",   True),
    }

    def __init__(self, theme: dict, scale: float, fmt: str = "HH:MM:SS"):
        super().__init__()
        h_fmt, m_fmt, s_fmt, show_ap = self._FMT_MAP.get(fmt, ("%H", "%M", "%S", False))
        self._h_fmt, self._m_fmt, self._s_fmt, self._show_ap = h_fmt, m_fmt, s_fmt, show_ap
        sc = lambda v: int(v * scale)

        # ClockSection 자체가 세로로 늘어나지 않도록 고정
        self.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Maximum)

        root = QVBoxLayout(self)
        root.setContentsMargins(0, 0, 0, sc(12))
        root.setSpacing(sc(6))

        # ── 날짜 ─────────────────────────────────────────────────────────
        df = display_font(sc(22), QFont.Medium)
        df.setLetterSpacing(QFont.AbsoluteSpacing, 0.4)
        self.date_lbl = QLabel()
        self.date_lbl.setFont(df)
        self.date_lbl.setStyleSheet(f"color:{theme['secondary']};")
        self.date_lbl.setAlignment(Qt.AlignCenter)
        root.addWidget(self.date_lbl)

        # ── 시간: HH:MM (큰 숫자) + 우측에 AM/PM(상) + :SS(하) ──────────
        time_row = QHBoxLayout()
        time_row.setContentsMargins(0, 0, 0, 0)
        time_row.setSpacing(sc(6))
        time_row.addStretch(1)

        hm_f = display_font(sc(64), QFont.Bold)
        self.hm_lbl = QLabel()
        self.hm_lbl.setFont(hm_f)
        self.hm_lbl.setStyleSheet(f"color:{theme['primary']};")
        time_row.addWidget(self.hm_lbl, alignment=Qt.AlignVCenter)

        # 순서: HM → SS (HH:MM 의 글자 baseline 에 맞춤) → AM/PM(중앙)
        if s_fmt:
            from PyQt5.QtGui import QFontMetrics
            self.sec_lbl = QLabel()
            sec_font = pick_font(sc(15), QFont.Medium)
            self.sec_lbl.setFont(sec_font)
            sec_color = theme.get("muted", theme["secondary"])
            self.sec_lbl.setStyleSheet(f"color:{sec_color};")
            # HM 폰트 descent 와 SS 폰트 descent 의 차이만큼 위로 끌어올림 → baseline 정렬
            hm_desc = QFontMetrics(hm_f).descent()
            ss_desc = QFontMetrics(sec_font).descent()
            self.sec_lbl.setContentsMargins(0, 0, 0, max(0, hm_desc - ss_desc))
            time_row.addWidget(self.sec_lbl, alignment=Qt.AlignBottom)
        else:
            self.sec_lbl = None

        if show_ap:
            self.ap_lbl = QLabel()
            af = pick_font(sc(20), QFont.Medium)
            af.setLetterSpacing(QFont.AbsoluteSpacing, 0.6)
            self.ap_lbl.setFont(af)
            self.ap_lbl.setStyleSheet(f"color:{theme['secondary']};")
            time_row.addWidget(self.ap_lbl, alignment=Qt.AlignVCenter)
        else:
            self.ap_lbl = None
        time_row.addStretch(1)
        root.addLayout(time_row)

        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(500)
        self._tick()

    def _tick(self):
        from datetime import datetime
        now = datetime.now()
        self.hm_lbl.setText(f"{now.strftime(self._h_fmt)}:{now.strftime(self._m_fmt)}")
        if self.sec_lbl is not None:
            self.sec_lbl.setText(now.strftime(self._s_fmt))
        if self.ap_lbl is not None:
            self.ap_lbl.setText(now.strftime("%p"))
        wd = _KO_WEEKDAY[now.weekday()]
        self.date_lbl.setText(
            f"{now.year}.{now.month:02d}.{now.day:02d}  {wd}요일"
        )


class IconBubble(QLabel):
    """아이콘 뒤에 부드러운 원 배경을 그려 밝은 벽지에서도 잘 보이게 함."""

    def __init__(self, theme: dict, size: int):
        super().__init__()
        self.theme = theme
        self._size = size
        self.setFixedSize(size, size)
        self.setAlignment(Qt.AlignCenter)

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # 배경: 라디얼 그라디언트 (테마별)
        is_dark = self.theme is DARK
        r = self._size / 2
        cx = cy = self._size / 2
        grad = QRadialGradient(cx, cy, r)
        if is_dark:
            grad.setColorAt(0.0, QColor(255, 255, 255, 18))
            grad.setColorAt(0.85, QColor(255, 255, 255, 8))
            grad.setColorAt(1.0, QColor(255, 255, 255, 0))
        else:
            grad.setColorAt(0.0, QColor(60, 80, 110, 30))
            grad.setColorAt(0.85, QColor(60, 80, 110, 12))
            grad.setColorAt(1.0, QColor(60, 80, 110, 0))
        p.setBrush(grad)
        p.setPen(Qt.NoPen)
        p.drawEllipse(self.rect())

        # 픽스맵 위에 그리기
        pix = self.pixmap()
        if pix is not None and not pix.isNull():
            x = (self.width()  - pix.width())  // 2
            y = (self.height() - pix.height()) // 2
            p.drawPixmap(x, y, pix)
        p.end()


class WeatherSection(QWidget):
    """좌측 Hero(아이콘+온도) + 우측 3×2 통계 그리드 + 하단 mood."""

    def __init__(self, theme: dict, scale: float, show_city: bool = True):
        super().__init__()
        self.theme = theme
        self.scale = scale
        s = lambda v: int(v * scale)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(s(8))

        # ── 1) 도시명 (옵션) ─────────────────────────────────────────────
        self.city_lbl = QLabel("로딩 중…")
        cf = pick_font(s(12), QFont.Medium)
        cf.setLetterSpacing(QFont.AbsoluteSpacing, 0.8)
        self.city_lbl.setFont(cf)
        self.city_lbl.setStyleSheet(f"color:{theme['secondary']};")
        self.city_lbl.setAlignment(Qt.AlignCenter)
        self.city_lbl.setVisible(show_city)
        outer.addWidget(self.city_lbl)

        # ── 2) Hero: [icon] | [mood + 온도 세로묶음] | [통계 3×2] ────────
        hero = QHBoxLayout()
        hero.setContentsMargins(0, 0, 0, 0)
        hero.setSpacing(s(20))
        hero.addStretch(1)

        # 좌측: 아이콘
        self._ico_size = s(140)
        self.icon_lbl = IconBubble(theme, self._ico_size)
        self.icon_lbl.setPixmap(emoji_pixmap("🌡️", int(self._ico_size * 0.78)))
        hero.addWidget(self.icon_lbl, alignment=Qt.AlignVCenter)

        # 가운데: 코멘트(작게) + 온도(크게) 세로 묶음 — 거리 최소화
        self.mood_lbl = QLabel("")
        mf = pick_font(s(12), QFont.Medium)
        mf.setItalic(True)
        self.mood_lbl.setFont(mf)
        self.mood_lbl.setStyleSheet(f"color:{theme['secondary']};")
        self.mood_lbl.setAlignment(Qt.AlignCenter)

        tf = display_font(s(72), QFont.Light)
        self.temp_lbl = QLabel("--°")
        self.temp_lbl.setFont(tf)
        self.temp_lbl.setStyleSheet(f"color:{theme['primary']};")
        self.temp_lbl.setAlignment(Qt.AlignCenter)

        center_col = QVBoxLayout()
        center_col.setContentsMargins(0, 0, 0, 0)
        center_col.setSpacing(0)
        center_col.addWidget(self.mood_lbl)
        center_col.addWidget(self.temp_lbl)
        center_w = QWidget()
        center_w.setLayout(center_col)
        center_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        hero.addWidget(center_w, alignment=Qt.AlignVCenter)

        # 우측: 3×2 통계 그리드
        from PyQt5.QtGui import QFontMetrics
        muted   = theme.get("muted", theme["secondary"])
        cap_fnt = pick_font(s(9), QFont.Medium)
        cap_fnt.setLetterSpacing(QFont.AbsoluteSpacing, 0.5)
        val_fnt = pick_font(s(13), QFont.Medium)

        # 가장 긴 텍스트("비올 확률") 폭에 맞춘 최소 셀 너비 + 패딩
        cap_metrics = QFontMetrics(cap_fnt)
        cell_min_w  = cap_metrics.horizontalAdvance("비올 확률") + s(16)

        def _make_stat(caption: str) -> tuple:
            cell = QVBoxLayout()
            cell.setContentsMargins(0, 0, 0, 0)
            cell.setSpacing(s(2))
            cap = QLabel(caption)
            cap.setFont(cap_fnt)
            cap.setStyleSheet(f"color:{muted};")
            cap.setAlignment(Qt.AlignCenter)
            val = QLabel("—")
            val.setFont(val_fnt)
            val.setStyleSheet(f"color:{theme['primary']};")
            val.setAlignment(Qt.AlignCenter)
            cell.addWidget(cap)
            cell.addWidget(val)
            w = QWidget()
            w.setLayout(cell)
            w.setMinimumWidth(cell_min_w)
            return w, val

        # 6 컬럼 trick — row 0 의 3칸이 각 2col span, row 1 의 2칸이
        # 각 2col span 이지만 1만큼 시프트되어 row 0 셀들 사이에 위치
        grid = QGridLayout()
        grid.setContentsMargins(0, 0, 0, 0)
        grid.setHorizontalSpacing(0)
        grid.setVerticalSpacing(s(10))
        for c in range(6):
            grid.setColumnStretch(c, 1)

        self._stat_high,  self.high_val  = _make_stat("최고")
        self._stat_low,   self.low_val   = _make_stat("최저")
        self._stat_feels, self.feels_val = _make_stat("체감")
        self._stat_rain,  self.rain_val  = _make_stat("비올 확률")
        self._stat_humid, self.humid_val = _make_stat("습도")

        # row 0: 3칸 균등 (각 2 col span)
        grid.addWidget(self._stat_high,  0, 0, 1, 2)
        grid.addWidget(self._stat_low,   0, 2, 1, 2)
        grid.addWidget(self._stat_feels, 0, 4, 1, 2)
        # row 1: 2칸 가운데 정렬 (1col 시프트 → row 0 셀들 사이)
        grid.addWidget(self._stat_rain,  1, 1, 1, 2)
        grid.addWidget(self._stat_humid, 1, 3, 1, 2)

        grid_w = QWidget()
        grid_w.setLayout(grid)
        grid_w.setSizePolicy(QSizePolicy.Preferred, QSizePolicy.Preferred)
        hero.addWidget(grid_w, alignment=Qt.AlignVCenter)

        hero.addStretch(1)
        outer.addLayout(hero)

        # 호환성용
        self.range_lbl  = QLabel()
        self.feels_lbl  = self.feels_val
        self.rain_lbl   = self.rain_val
        self.humid_lbl  = self.humid_val
        self.wind_lbl   = QLabel()
        self.detail_lbl = self.feels_lbl

    def update_data(self, d: WeatherData, unit: str = "C") -> None:
        from datetime import datetime
        t  = d.temp_c if unit == "C" else d.temp_c * 9 / 5 + 32
        ft = d.feels_like_c if unit == "C" else d.feels_like_c * 9 / 5 + 32
        if unit == "C":
            tmax, tmin = d.temp_max_c, d.temp_min_c
        else:
            tmax = d.temp_max_c * 9 / 5 + 32
            tmin = d.temp_min_c * 9 / 5 + 32

        emoji = desc_to_emoji(d.condition, datetime.now().hour)
        self.icon_lbl.setFixedSize(self._ico_size, self._ico_size)
        self.icon_lbl.setPixmap(emoji_pixmap(emoji, int(self._ico_size * 0.78)))
        self.city_lbl.setText(d.city)
        self.temp_lbl.setText(f"{t:.0f}°")
        self.high_val.setText(f"{tmax:.0f}°")
        self.low_val.setText(f"{tmin:.0f}°")
        self.feels_val.setText(f"{ft:.0f}°")
        self.rain_val.setText(f"{d.rain_pct}%")
        self.humid_val.setText(f"{d.humidity}%")
        self.mood_lbl.setText(fetcher.weather_mood(d))

    def set_error(self, msg: str) -> None:
        self.city_lbl.setText("날씨 정보 없음")
        self.temp_lbl.setText("--°")
        for lbl in (self.high_val, self.low_val, self.feels_val,
                    self.rain_val, self.humid_val):
            lbl.setText("—")
        self.mood_lbl.setText(msg[:60])


class HourlyCell(QWidget):
    """시간 / 아이콘 / 온도 한 칸."""

    def __init__(self, theme: dict, scale: float):
        super().__init__()
        self.scale = scale
        self._theme = theme
        s = lambda v: int(v * scale)

        v = QVBoxLayout(self)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(s(3))
        v.setAlignment(Qt.AlignHCenter)

        self.time_lbl = QLabel("--")
        self.time_lbl.setFont(pick_font(s(11)))
        self.time_lbl.setStyleSheet(f"color:{theme['secondary']};")
        self.time_lbl.setAlignment(Qt.AlignCenter)

        self._ico_size = s(52)   # 40 → 52 (1.3x)
        self.icon_lbl = IconBubble(theme, self._ico_size)

        self.temp_lbl = QLabel("--°")
        self.temp_lbl.setFont(pick_font(s(13), QFont.Medium))
        self.temp_lbl.setStyleSheet(f"color:{theme['primary']};")
        self.temp_lbl.setAlignment(Qt.AlignCenter)

        v.addWidget(self.time_lbl)
        v.addWidget(self.icon_lbl, alignment=Qt.AlignCenter)
        v.addWidget(self.temp_lbl)

    def update_data(self, slot) -> None:
        self.time_lbl.setText(f"{slot.dt:%H:%M}")
        inner = int(self._ico_size * 0.78)
        self.icon_lbl.setPixmap(
            emoji_pixmap(desc_to_emoji(slot.desc, slot.dt.hour), inner)
        )
        self.temp_lbl.setText(f"{slot.temp_c:.0f}°")

    def clear(self) -> None:
        self.time_lbl.setText("")
        self.icon_lbl.clear()
        self.temp_lbl.setText("")


class HourlyStrip(QWidget):
    """5칸의 시간별 예보."""

    def __init__(self, theme: dict, scale: float, count: int = 5):
        super().__init__()
        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(0)
        self.cells: list = []
        for _ in range(count):
            c = HourlyCell(theme, scale)
            h.addWidget(c, 1)
            self.cells.append(c)

    def update_data(self, hourly: list) -> None:
        for cell, slot in zip(self.cells, hourly):
            cell.update_data(slot)
        for cell in self.cells[len(hourly):]:
            cell.clear()


try:
    import psutil as _psutil
    _HAS_PSUTIL = True
except ImportError:
    _psutil = None  # type: ignore
    _HAS_PSUTIL = False

# CPU 온도: WMI ThermalZone (관리자 권한 불필요)
try:
    import wmi as _wmi_mod
    _wmi_thermal = _wmi_mod.WMI()
    _wmi_thermal.Win32_PerfFormattedData_Counters_ThermalZoneInformation()
    _HAS_TEMP = True
except Exception:
    _wmi_thermal = None
    _HAS_TEMP = False


def _read_cpu_temp() -> Optional[float]:
    """ACPI 열구역 온도 평균 반환 (°C). 실패 시 None."""
    try:
        zones = _wmi_thermal.Win32_PerfFormattedData_Counters_ThermalZoneInformation()
        if zones:
            temps = [(z.HighPrecisionTemperature / 10) - 273.15 for z in zones]
            return sum(temps) / len(temps)
    except Exception:
        pass
    return None


class SystemSection(QWidget):
    """CPU / RAM / 온도 — 단일 가로 라인 컴팩트 표시 (가운데 정렬, 개별 토글)."""

    def __init__(self, theme: dict, scale: float,
                 show_cpu: bool = True, show_ram: bool = True, show_temp: bool = True):
        super().__init__()
        self.theme = theme
        s = lambda v: int(v * scale)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, 0, 0, 0)
        h.setSpacing(s(32))
        h.addStretch()  # 좌측 여백 → 가운데 정렬

        font = pick_font(s(10), QFont.Medium)
        sys_color = theme.get("muted", theme["secondary"])

        def _pill(prefix: str) -> QLabel:
            lbl = QLabel(f"{prefix} —")
            lbl.setFont(font)
            lbl.setStyleSheet(f"color:{sys_color};")
            h.addWidget(lbl)
            return lbl

        self.cpu_lbl  = _pill("⚡") if show_cpu else None
        self.ram_lbl  = _pill("💾") if show_ram else None
        self.temp_lbl = _pill("🌡") if (show_temp and _HAS_TEMP) else None
        h.addStretch()  # 우측 여백 → 가운데 정렬

        need_psutil = (self.cpu_lbl is not None) or (self.ram_lbl is not None)
        if _HAS_PSUTIL and need_psutil:
            self._timer = QTimer(self)
            self._timer.timeout.connect(self._tick)
            self._timer.start(2000)
            self._tick()
        elif need_psutil and self.cpu_lbl is not None:
            self.cpu_lbl.setText("⚡ psutil 없음")

        if self.temp_lbl is not None:
            self._temp_timer = QTimer(self)
            self._temp_timer.timeout.connect(self._tick_temp)
            self._temp_timer.start(5000)
            self._tick_temp()

    def _tick(self) -> None:
        if self.cpu_lbl is not None:
            cpu = _psutil.cpu_percent(interval=None)
            self.cpu_lbl.setText(f"⚡ {cpu:.0f}%")
        if self.ram_lbl is not None:
            mem = _psutil.virtual_memory()
            used = mem.used / (1024 ** 3)
            self.ram_lbl.setText(f"💾 {used:.1f}GB ({mem.percent:.0f}%)")

    def _tick_temp(self) -> None:
        t = _read_cpu_temp()
        if t is not None and self.temp_lbl is not None:
            self.temp_lbl.setText(f"🌡 {t:.0f}°C")
            normal = self.theme.get("muted", self.theme["secondary"])
            color = self.theme["down"] if t >= 80 else normal
            self.temp_lbl.setStyleSheet(f"color:{color};")


def _resolve_lnk_target(lnk_path: str) -> Optional[str]:
    """Windows .lnk 파일을 타겟 실행파일 경로로 resolve. UWP는 빈 문자열."""
    try:
        import win32com.client
        sh = win32com.client.Dispatch("WScript.Shell")
        sc = sh.CreateShortCut(lnk_path)
        target = sc.TargetPath
        if target and Path(target).exists():
            return target
    except Exception as ex:
        _log(f"lnk resolve 실패 {lnk_path}: {ex}")
    return None


def _icon_via_shell(path: str, size: int) -> Optional[QPixmap]:
    """SHGetFileInfo 로 아이콘 추출. SHGFI_LINKOVERLAY 미지정 → 화살표 없음."""
    if sys.platform != "win32":
        return None
    try:
        import ctypes
        from ctypes import wintypes, byref, c_int

        class SHFILEINFO(ctypes.Structure):
            _fields_ = [
                ("hIcon",         wintypes.HANDLE),
                ("iIcon",         c_int),
                ("dwAttributes",  wintypes.DWORD),
                ("szDisplayName", ctypes.c_wchar * 260),
                ("szTypeName",    ctypes.c_wchar * 80),
            ]

        SHGFI_ICON      = 0x000000100
        SHGFI_LARGEICON = 0x000000000   # 32x32

        info = SHFILEINFO()
        result = ctypes.windll.shell32.SHGetFileInfoW(
            path, 0, byref(info), ctypes.sizeof(info),
            SHGFI_ICON | SHGFI_LARGEICON,
        )
        if not result or not info.hIcon:
            return None

        from PyQt5.QtWinExtras import QtWin
        pix = QtWin.fromHICON(info.hIcon)
        ctypes.windll.user32.DestroyIcon(info.hIcon)
        if pix is None or pix.isNull():
            return None
        return pix.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    except Exception as ex:
        _log(f"shell icon 실패 {path}: {ex}")
        return None


def _icon_for_path(path: str, size: int) -> QPixmap:
    """경로에 대한 아이콘 픽스맵. SHGetFileInfo(점보) 우선 사용."""
    # 1. 시스템 점보 아이콘 (256x256, 오버레이 없음)
    pix = _icon_via_shell(path, size)
    if pix is not None and not pix.isNull():
        return pix

    # 2. .lnk 면 타겟 resolve 해서 다시 시도
    actual = path
    if path.lower().endswith(".lnk"):
        target = _resolve_lnk_target(path)
        if target:
            actual = target
            pix = _icon_via_shell(actual, size)
            if pix is not None and not pix.isNull():
                return pix

    # 3. QFileIconProvider fallback
    from PyQt5.QtCore    import QFileInfo
    from PyQt5.QtWidgets import QFileIconProvider
    icon = QFileIconProvider().icon(QFileInfo(actual))
    src = icon.pixmap(256, 256)
    if src.isNull():
        src = icon.pixmap(size, size)
    return src.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)


def _launch_path(path: str) -> None:
    """경로 실행. UWP/일반 모두 지원."""
    import os
    norm = os.path.normpath(path)
    if not Path(norm).exists():
        _log(f"파일 없음: {norm}")
        return
    try:
        os.startfile(norm)
        return
    except Exception:
        pass
    try:
        import subprocess
        subprocess.Popen(["explorer.exe", norm], shell=False)
    except Exception as ex:
        _log(f"실행 실패 {norm}: {ex}")


_LAUNCHER_MIME = "application/x-launcher-tile"


class LauncherTile(QWidget):
    """앱 실행 타일 — 호버/클릭 효과 + 좌클릭 실행 + 우클릭 삭제 + 드래그 reorder."""
    removed = pyqtSignal(str)

    def __init__(self, path: str, theme: dict, scale: float):
        super().__init__()
        self.path  = path
        self.theme = theme
        s = lambda v: int(v * scale)
        ico = s(72)
        pad = s(8)
        self._radius  = s(12)
        self._hovered     = False
        self._pressed     = False
        self._dragged     = False    # 드래그 중에는 그리지 않음 (커서 픽스맵과 겹침 방지)
        self._dragged_now = False    # 이번 mouseDown 사이클에서 드래그가 발동됐는지
        self._press_pos: Optional[QPoint] = None

        self.setFixedSize(ico + pad * 2, ico + pad * 2)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(Path(path).stem)

        self._pixmap = _icon_for_path(path, ico)
        self._ico_size = ico
        self._pad = pad

    def paintEvent(self, e):
        if self._dragged:
            return   # 드래그 중에는 placeholder (공간만 차지)
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setRenderHint(QPainter.SmoothPixmapTransform)

        # 호버/클릭 배경
        if self._pressed:
            alpha = 60
        elif self._hovered:
            alpha = 30
        else:
            alpha = 0
        if alpha > 0:
            is_dark = self.theme is DARK
            color = QColor(255, 255, 255, alpha) if is_dark else QColor(0, 0, 0, alpha)
            p.setBrush(color)
            p.setPen(Qt.NoPen)
            p.drawRoundedRect(self.rect(), self._radius, self._radius)

        # 아이콘 (눌렸을 때 살짝 축소)
        scale = 0.94 if self._pressed else 1.0
        sz = int(self._ico_size * scale)
        x = (self.width()  - sz) // 2
        y = (self.height() - sz) // 2
        p.drawPixmap(x, y, sz, sz, self._pixmap)
        p.end()

    def enterEvent(self, e):
        self._hovered = True
        self.update()

    def leaveEvent(self, e):
        self._hovered = False
        self._pressed = False
        self.update()

    # Hi-DPI 환경에서 손가락 떨림으로 인한 오작동 방지 위해 임계값 충분히 크게
    _DRAG_THRESHOLD = 16

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._pressed     = True
            self._dragged_now = False
            self._press_pos   = e.pos()
            self.update()
            e.accept()
        elif e.button() == Qt.RightButton:
            m = QMenu(self)
            m.setStyleSheet(_menu_qss(self.theme))
            act = m.addAction(f"'{Path(self.path).stem}' 삭제")
            if m.exec_(e.globalPos()) is act:
                self.removed.emit(self.path)
            e.accept()

    def mouseMoveEvent(self, e):
        if not (e.buttons() & Qt.LeftButton) or self._press_pos is None:
            return
        if (e.pos() - self._press_pos).manhattanLength() < self._DRAG_THRESHOLD:
            return
        # 드래그 시작
        from PyQt5.QtCore import QMimeData
        from PyQt5.QtGui  import QDrag
        self._pressed     = False
        self._dragged_now = True
        self.update()
        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(_LAUNCHER_MIME, self.path.encode("utf-8"))
        drag.setMimeData(mime)
        drag.setPixmap(self._pixmap)
        drag.setHotSpot(self._pixmap.rect().center())
        drag.exec_(Qt.MoveAction)
        # 드래그 종료 후 placeholder 복구
        parent = self.parentWidget()
        while parent is not None and not isinstance(parent, LauncherSection):
            parent = parent.parentWidget()
        if isinstance(parent, LauncherSection):
            parent._end_live_drag(commit=True)
        self._press_pos = None

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            was_pressed = self._pressed
            was_dragged = self._dragged_now
            self._pressed     = False
            self._dragged_now = False
            self.update()
            # 드래그가 발동되지 않았으면 클릭으로 간주 → 실행
            if was_pressed and not was_dragged:
                _launch_path(self.path)
            e.accept()
        self._press_pos = None


class LauncherSection(QWidget):
    """앱 런처 — 드래그앤드롭으로 추가, 클릭으로 실행."""
    changed = pyqtSignal(list)

    def __init__(self, programs: list, theme: dict, scale: float):
        super().__init__()
        self.theme = theme
        self.scale = scale
        self.programs: list = list(programs)
        self.setAcceptDrops(True)
        self._tiles: dict = {}     # path -> LauncherTile (재사용 → 애니메이션)
        self._anims: list = []     # 진행중 애니메이션
        self._drag_src: Optional[str] = None    # 라이브 드래그 중인 타일 경로

        s = lambda v: int(v * scale)

        outer = QVBoxLayout(self)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.setSpacing(s(6))

        self.row = QHBoxLayout()
        self.row.setContentsMargins(0, 0, 0, 0)
        self.row.setSpacing(s(10))
        outer.addLayout(self.row)

        self.empty_lbl = QLabel("프로그램·바로가기를 여기로 끌어다 놓으세요")
        self.empty_lbl.setFont(pick_font(s(9)))
        self.empty_lbl.setStyleSheet(f"color:{theme['secondary']};")
        self.empty_lbl.setAlignment(Qt.AlignCenter)
        outer.addWidget(self.empty_lbl)

        self._rebuild()

    def _clear_row(self):
        """row 안의 layout item 만 제거 (위젯은 삭제하지 않음)."""
        while self.row.count():
            self.row.takeAt(0)

    def _rebuild(self, animate: bool = False, duration: int = 220):
        # 진행 중 애니메이션 정리
        for a in list(self._anims):
            a.stop()
        self._anims.clear()

        # 애니메이션 시작 전 기존 위치 캡처
        old_pos = {}
        if animate:
            for path, tile in self._tiles.items():
                old_pos[path] = tile.pos()

        # programs 에 없는 타일은 삭제
        for path in list(self._tiles.keys()):
            if path not in self.programs:
                tile = self._tiles.pop(path)
                tile.setParent(None)
                tile.deleteLater()

        # row 비우기 (위젯 삭제 X)
        self._clear_row()

        # 좌 stretch + 타일들 + 우 stretch
        self.row.addStretch()
        for path in self.programs:
            tile = self._tiles.get(path)
            if tile is None:
                tile = LauncherTile(path, self.theme, self.scale)
                tile.removed.connect(self._on_remove)
                self._tiles[path] = tile
            self.row.addWidget(tile)
        self.row.addStretch()

        self.empty_lbl.setVisible(len(self.programs) == 0)

        # 애니메이션: 새 위치 계산 후 옛 위치에서 슬라이드
        if animate and old_pos:
            self.row.activate()   # 새 layout 위치만 적용 (paint flush 안 함 → 깜빡임 방지)
            for path, tile in self._tiles.items():
                old = old_pos.get(path)
                new = tile.pos()
                if old is None or old == new:
                    continue
                tile.move(old)    # 옛 위치로 되돌리고 (paint 는 아직 안 됨)
                anim = QPropertyAnimation(tile, b"pos", self)
                anim.setStartValue(old)
                anim.setEndValue(new)
                anim.setDuration(duration)
                anim.setEasingCurve(QEasingCurve.OutCubic)
                anim.finished.connect(lambda a=anim: self._anims.remove(a) if a in self._anims else None)
                self._anims.append(anim)
                anim.start()

    def _on_remove(self, path: str):
        if path in self.programs:
            self.programs.remove(path)
            self._rebuild(animate=True)
            self.changed.emit(self.programs)

    def add_paths(self, paths: list):
        added = False
        for p in paths:
            if p and p not in self.programs and Path(p).exists():
                self.programs.append(p)
                added = True
        if added:
            self._rebuild(animate=True)
            self.changed.emit(self.programs)

    def _accept_kinds(self, e) -> bool:
        return e.mimeData().hasUrls() or e.mimeData().hasFormat(_LAUNCHER_MIME)

    def _index_at_x(self, x: int) -> int:
        """x 좌표가 어느 타일 인덱스에 해당하는지."""
        idx = 0
        for i in range(self.row.count()):
            w = self.row.itemAt(i).widget()
            if w is None:
                continue
            mid = w.x() + w.width() // 2
            if x < mid:
                return idx
            idx += 1
        return idx

    def _begin_live_drag(self, src_path: str):
        """라이브 reorder 시작 — 원본 타일은 placeholder 처리."""
        self._drag_src = src_path
        tile = self._tiles.get(src_path)
        if tile is not None:
            tile._dragged = True
            tile.update()

    def _end_live_drag(self, commit: bool):
        """드래그 종료 — placeholder 해제."""
        if self._drag_src is None:
            return
        tile = self._tiles.get(self._drag_src)
        if tile is not None:
            tile._dragged = False
            tile.update()
        if commit:
            self.changed.emit(self.programs)
        self._drag_src = None

    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_LAUNCHER_MIME):
            src = bytes(e.mimeData().data(_LAUNCHER_MIME)).decode("utf-8")
            if src in self.programs:
                self._begin_live_drag(src)
            e.acceptProposedAction()
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(_LAUNCHER_MIME) and self._drag_src:
            src = self._drag_src
            new_idx = self._index_at_x(e.pos().x())
            if src in self.programs:
                old = self.programs.index(src)
                if new_idx > old:
                    new_idx -= 1
                new_idx = max(0, min(len(self.programs) - 1, new_idx))
                if new_idx != old:
                    self.programs.pop(old)
                    self.programs.insert(new_idx, src)
                    self._rebuild(animate=True, duration=480)
            e.acceptProposedAction()
        elif e.mimeData().hasUrls():
            e.acceptProposedAction()

    def dragLeaveEvent(self, e):
        # 위젯 밖으로 나갔다가 다시 들어올 수 있으므로 placeholder 만 잠시 해제하지 않음
        # → drop / 외부 cancel 시점에 _end_live_drag 호출됨
        pass

    def dropEvent(self, e):
        # reorder (이미 라이브로 정렬됨)
        if e.mimeData().hasFormat(_LAUNCHER_MIME):
            self._end_live_drag(commit=True)
            e.acceptProposedAction()
            return
        # 새 프로그램 추가
        if e.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
            self.add_paths(paths)
            e.acceptProposedAction()


class StockRow(QWidget):
    removed = pyqtSignal(str)

    def __init__(self, ticker: str, theme: dict, scale: float):
        super().__init__()
        self.theme  = theme
        self.ticker = ticker
        s = lambda v: int(v * scale)

        h = QHBoxLayout(self)
        h.setContentsMargins(0, s(5), 0, s(5))
        h.setSpacing(s(4))

        self.ticker_lbl = QLabel(ticker)
        self.ticker_lbl.setFont(pick_font(s(10), QFont.Medium))
        self.ticker_lbl.setFixedWidth(s(112))
        self.ticker_lbl.setStyleSheet(f"color:{theme['secondary']};")

        self.price_lbl = QLabel("…")
        self.price_lbl.setFont(pick_font(s(11)))
        self.price_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.price_lbl.setStyleSheet(f"color:{theme['primary']};")
        self.price_lbl.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)

        self.change_lbl = QLabel("")
        self.change_lbl.setFont(pick_font(s(10), QFont.Medium))
        self.change_lbl.setFixedWidth(s(86))
        self.change_lbl.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.change_lbl.setStyleSheet(f"color:{theme['secondary']};")

        h.addWidget(self.ticker_lbl)
        h.addWidget(self.price_lbl)
        h.addWidget(self.change_lbl)

    def update_data(self, d: StockData) -> None:
        if d.error:
            self.price_lbl.setText("--")
            self.change_lbl.setText("오류")
            self.change_lbl.setStyleSheet(f"color:{self.theme['secondary']};")
            return
        is_krw = d.currency == "KRW"
        self.price_lbl.setText(f"₩{d.price:,.0f}" if is_krw else f"${d.price:,.2f}")
        arrow = "▲" if d.change >= 0 else "▼"
        color = self.theme["up"] if d.change >= 0 else self.theme["down"]
        self.change_lbl.setText(f"{arrow} {d.change_pct:+.2f}%")
        self.change_lbl.setStyleSheet(f"color:{color};")

    def contextMenuEvent(self, e):
        m = QMenu(self)
        m.setStyleSheet(_menu_qss(self.theme))
        act = m.addAction(f"'{self.ticker}' 삭제")
        if m.exec_(e.globalPos()) is act:
            self.removed.emit(self.ticker)


# ─── 커서 필터 ────────────────────────────────────────────────────────────────

class _EdgeCursorFilter(QObject):
    """앱 전체 마우스무브 이벤트를 가로채 오른쪽 엣지 위에서 커서를 바꿔줌.
    child 위젯이 이벤트를 먹어도 parent mouseMoveEvent 가 불리지 않는 문제를 우회."""
    def __init__(self, widget: "MainWidget"):
        super().__init__(widget)
        self._w = widget
        QApplication.instance().installEventFilter(self)

    def eventFilter(self, obj, e) -> bool:
        if e.type() == QEvent.MouseMove:
            gp  = QCursor.pos()
            lp  = self._w.mapFromGlobal(gp)
            if 0 <= lp.x() <= self._w.width() and 0 <= lp.y() <= self._w.height():
                edge = self._w._edge_at(lp)
                self._w.setCursor(self._w._cursor_for_edge(edge))
        return False


# ─── 메인 위젯 ────────────────────────────────────────────────────────────────

class MainWidget(QWidget):
    REFRESH_WEATHER_MS = 30 * 60 * 1000
    REFRESH_STOCKS_MS  =  5 * 60 * 1000

    def __init__(self):
        super().__init__()
        self.cfg     = load_config()
        self.theme   = LIGHT if self.cfg.get("theme") == "light" else DARK
        self.scale_f = SCALE_FACTORS.get(self.cfg.get("scale", "M"), 1.0)

        self.pool = QThreadPool.globalInstance()
        self.pool.setMaxThreadCount(2)   # 네트워크 fetch 만 사용 → 2 스레드 충분
        self.sig  = _Signals()
        self.sig.weather_done.connect(self._on_weather)
        self.sig.stocks_done.connect(self._on_stocks)

        # Qt 픽스맵 캐시 한도 축소 (기본 10MB → 1MB)
        from PyQt5.QtGui import QPixmapCache
        QPixmapCache.setCacheLimit(1024)

        self._drag_pos: Optional[QPoint] = None
        self._resize_dir: str = ""
        self._resize_start: Optional[QPoint] = None
        self._resize_orig_w: int = 0
        self._resize_orig_h: int = 0
        self._desktop_active: bool = False  # Show Desktop 상태 추적
        self._stock_rows: list = []
        self._show_border: bool = False

        self._init_window()
        self._build_ui()
        self._init_tray()
        self._init_timers()

        self.move(self.cfg.get("pos_x", 100), self.cfg.get("pos_y", 100))
        self.refresh_all()

    def _init_window(self):
        self._update_window_flags()
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_NoSystemBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAutoFillBackground(False)
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        _EdgeCursorFilter(self)
        self._update_stylesheet()
        s = lambda v: int(v * self.scale_f)
        default_w = s(520)
        w = self.cfg.get("width_px", default_w)
        if w < s(400):
            w = default_w
        h = self.cfg.get("height_px", 100)
        self.setMinimumWidth(s(260))
        self.setMaximumWidth(s(1400))
        self.resize(w, h)
        # 영구 래퍼 레이아웃 — _build_ui 가 여기에 content 위젯을 붙임
        self._wrapper = QVBoxLayout(self)
        self._wrapper.setContentsMargins(0, 0, 0, 0)
        self._wrapper.setSpacing(0)
        self._content: Optional[QWidget] = None

    def _update_window_flags(self):
        flags = Qt.FramelessWindowHint | Qt.Tool
        if not self.cfg.get("pinned", True):
            flags |= Qt.WindowStaysOnTopHint
        self.setWindowFlags(flags)

    def _update_stylesheet(self):
        self.setStyleSheet(
            f"QWidget {{ font-family: {FONT_STACK}; color: {self.theme['primary']};"
            "  background: transparent; }"
            "QLabel, QPushButton { background: transparent; }"
        )

    def _apply_native_effects(self):
        hwnd = int(self.winId())
        _apply_glass(hwnd, dark=(self.theme is DARK))
        if self.cfg.get("pinned", True):
            _send_to_bottom(hwnd)
        self._apply_rounded_mask()

    def _apply_rounded_mask(self):
        """DWM 코너 대신 Qt setMask 로 둥근 코너 구현 — 그림자/테두리 없음."""
        radius = int(20 * self.scale_f)
        path = QPainterPath()
        path.addRoundedRect(QRectF(self.rect()), radius, radius)
        self.setMask(QRegion(path.toFillPolygon().toPolygon()))

    def _build_ui(self):
        # 기존 content 위젯 제거 (재빌드 시)
        if self._content is not None:
            self._content.setParent(None)
            self._content.deleteLater()
            self._content = None
            QApplication.processEvents()

        s = lambda v: int(v * self.scale_f)
        self._content = QWidget(self)
        self._content.setAttribute(Qt.WA_TranslucentBackground)
        self._wrapper.addWidget(self._content)

        body = QVBoxLayout(self._content)
        body.setContentsMargins(s(26), s(16), s(26), s(20))
        body.setSpacing(s(14))

        # 균등 stretch — 세로로 늘릴 때 각 섹션 사이에 동일한 간격이 들어감
        def _gap():
            body.addStretch(1)

        # ─ 시스템 (최상단) ───────────────────────────────────────────────
        show_cpu  = self.cfg.get("show_cpu",  True)
        show_ram  = self.cfg.get("show_ram",  True)
        show_temp = self.cfg.get("show_temp", True)
        if show_cpu or show_ram or show_temp:
            self.system_section = SystemSection(
                self.theme, self.scale_f,
                show_cpu=show_cpu, show_ram=show_ram, show_temp=show_temp,
            )
            body.addWidget(self.system_section)
            _gap()
        else:
            self.system_section = None

        # ─ 시계 ──────────────────────────────────────────────────────────
        if self.cfg.get("show_clock", True):
            self.clock_section = ClockSection(
                self.theme, self.scale_f, self.cfg.get("time_format", "HH:MM:SS")
            )
            body.addWidget(self.clock_section)
            _gap()
        else:
            self.clock_section = None

        # ─ 날씨 ──────────────────────────────────────────────────────────
        self.weather_section = WeatherSection(
            self.theme, self.scale_f,
            show_city=self.cfg.get("show_city", True),
        )
        body.addWidget(self.weather_section)
        _gap()

        # ─ 시간별 예보 ──────────────────────────────────────────────────
        self.hourly_strip = HourlyStrip(self.theme, self.scale_f)
        body.addWidget(self.hourly_strip)
        _gap()

        # ─ 주식 (옵션) ──────────────────────────────────────────────────
        if self.cfg.get("show_stocks", True):
            body.addWidget(self._divider(s))

            hdr = QHBoxLayout()
            hdr.setContentsMargins(0, 0, 0, 0)
            hdr_lbl = QLabel("주식")
            _hf = pick_font(s(9), QFont.Medium)
            _hf.setLetterSpacing(QFont.AbsoluteSpacing, 1.4)
            hdr_lbl.setFont(_hf)
            hdr_lbl.setStyleSheet(f"color:{self.theme['secondary']};")
            hdr.addWidget(hdr_lbl)
            hdr.addStretch()

            self.add_btn = QPushButton("＋")
            self.add_btn.setFixedSize(s(24), s(24))
            self.add_btn.setCursor(Qt.PointingHandCursor)
            self.add_btn.setStyleSheet(
                "QPushButton {"
                f"  background:transparent; color:{self.theme['secondary']};"
                f"  border:1px solid rgba(150,165,195,90); border-radius:{s(12)}px;"
                f"  font-size:{s(13)}px; padding-bottom:2px;"
                "}"
                "QPushButton:hover {"
                f"  color:{self.theme['accent']}; border-color:{self.theme['accent']};"
                "}"
            )
            self.add_btn.clicked.connect(self._quick_add_stock)
            hdr.addWidget(self.add_btn)
            body.addLayout(hdr)

            self.stocks_box = QWidget()
            self.stocks_layout = QVBoxLayout(self.stocks_box)
            self.stocks_layout.setContentsMargins(0, 0, 0, 0)
            self.stocks_layout.setSpacing(s(2))
            body.addWidget(self.stocks_box)
        else:
            self.stocks_box    = None
            self.stocks_layout = None
            self.add_btn       = None

        # ─ 앱 런처 (하단) ──────────────────────────────────────────────
        if self.cfg.get("show_launcher", True):
            body.addWidget(self._divider(s))
            self.launcher_section = LauncherSection(
                self.cfg.get("programs", []), self.theme, self.scale_f
            )
            self.launcher_section.changed.connect(self._on_programs_changed)
            body.addWidget(self.launcher_section)
        else:
            self.launcher_section = None

        self._rebuild_stock_rows()

    def _on_programs_changed(self, programs: list):
        self.cfg["programs"] = programs
        save_config(self.cfg)

    def _divider(self, s):
        d = QWidget()
        d.setFixedHeight(1)
        d.setStyleSheet(f"background:{self.theme['divider']};")
        return d

    def _rebuild_stock_rows(self):
        for row in self._stock_rows:
            row.deleteLater()
        self._stock_rows.clear()
        if self.stocks_layout is None:
            return
        for ticker in self.cfg.get("stocks", []):
            row = StockRow(ticker, self.theme, self.scale_f)
            row.removed.connect(self._remove_stock)
            self.stocks_layout.addWidget(row)
            self._stock_rows.append(row)

    # ── 트레이 ───────────────────────────────────────────────────────────────

    def _init_tray(self):
        self.tray = QSystemTrayIcon(self._make_tray_icon(), self)
        menu = QMenu()
        menu.setStyleSheet(_menu_qss(self.theme))

        self._toggle_action = QAction("보이기 / 숨기기", self)
        self._toggle_action.triggered.connect(self._toggle_visible)
        menu.addAction(self._toggle_action)

        for label, fn in [
            ("새로고침", self.refresh_all),
            ("설정...",  self._open_settings),
            (None, None),
            ("종료",     QApplication.quit),
        ]:
            if label is None:
                menu.addSeparator()
            else:
                a = QAction(label, self)
                a.triggered.connect(fn)
                menu.addAction(a)

        # 메뉴 열 때마다 상태 표시 갱신
        menu.aboutToShow.connect(self._refresh_tray_menu)

        self.tray.setContextMenu(menu)
        self.tray.setToolTip("날씨 · 주식 위젯")
        self.tray.activated.connect(
            lambda r: self._toggle_visible() if r == QSystemTrayIcon.Trigger else None
        )
        self.tray.show()
        self._refresh_tray_menu()

    def _refresh_tray_menu(self):
        """현재 가시성에 따라 토글 메뉴 텍스트 갱신."""
        visible = self.isVisible() and not self.isHidden()
        dot = "●" if visible else "○"
        self._toggle_action.setText(f"{dot}  보이기 / 숨기기")

    def _make_tray_icon(self) -> QIcon:
        ico = Path(__file__).parent / "widget.ico"
        return QIcon(str(ico)) if ico.exists() else QIcon()

    def _toggle_visible(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self._apply_native_effects()

    # ── 타이머 ───────────────────────────────────────────────────────────────

    def _init_timers(self):
        for ms, fn in [
            (self.REFRESH_WEATHER_MS, self._refresh_weather),
            (self.REFRESH_STOCKS_MS,  self._refresh_stocks),
        ]:
            t = QTimer(self)
            t.timeout.connect(fn)
            t.start(ms)

        # Show Desktop / Win+D 로 숨겨진 경우 자동 재표시
        self._dt_timer = QTimer(self)
        self._dt_timer.timeout.connect(self._check_desktop_visibility)
        self._dt_timer.start(200)

        # 주기적 메모리 정리 (Working Set trim) — 5분마다
        self._mem_timer = QTimer(self)
        self._mem_timer.timeout.connect(_trim_memory)
        self._mem_timer.start(5 * 60 * 1000)
        # 시작 직후 한 번 trim (UI 안정화 후)
        QTimer.singleShot(3000, _trim_memory)

    def _check_desktop_visibility(self):
        """Show Desktop / Win+D / 3-finger swipe 감지 후 위젯 재표시 + z-order 조정.
        상태 전환 시에만 z-order 변경 (깜빡임 방지)."""
        if not self.cfg.get("pinned", True):
            return
        if sys.platform != "win32":
            return
        if self.isHidden():
            return
        try:
            import ctypes
            user32 = ctypes.windll.user32
            hwnd = int(self.winId())

            # foreground 클래스 검사 → 바탕화면 활성 여부
            fg = user32.GetForegroundWindow()
            desktop_active = False
            if fg:
                buf = ctypes.create_unicode_buffer(256)
                user32.GetClassNameW(fg, buf, 256)
                if buf.value in ("Progman", "WorkerW"):
                    desktop_active = True

            # 위젯이 minimize/hidden 이면 무조건 복원
            if user32.IsIconic(hwnd):
                user32.ShowWindow(hwnd, 9)    # SW_RESTORE
                _log("위젯 minimized → 복원")
            elif not user32.IsWindowVisible(hwnd):
                user32.ShowWindow(hwnd, 4)    # SW_SHOWNOACTIVATE
                _log("위젯 hidden → 재표시")

            # 상태 전환 감지
            if desktop_active != self._desktop_active:
                self._desktop_active = desktop_active
                if desktop_active:
                    # Show Desktop 진입 → 바탕화면 위로 올림
                    user32.SetWindowPos(hwnd, 0, 0, 0, 0, 0,
                                         0x0001 | 0x0002 | 0x0010 | 0x0040)
                    _log("Show Desktop 진입 → 위젯 위로")
                else:
                    # Show Desktop 종료 → 다시 z-bottom 으로 (다른 앱에 가려지는 핀 모드)
                    _send_to_bottom(hwnd)
                    _log("Show Desktop 종료 → 위젯 z-bottom")
        except Exception as ex:
            _log(f"visibility 점검 오류: {ex}")

    # ── 데이터 ───────────────────────────────────────────────────────────────

    def refresh_all(self):
        self._refresh_weather()
        self._refresh_stocks()

    def _refresh_weather(self):
        self.pool.start(WeatherWorker(self.cfg["city"], self.sig))

    def _refresh_stocks(self):
        if self.cfg.get("stocks"):
            self.pool.start(StocksWorker(self.cfg["stocks"], self.sig))

    def _on_weather(self, result):
        if isinstance(result, Exception):
            self.weather_section.set_error(str(result))
        else:
            self.weather_section.update_data(result, self.cfg.get("unit", "C"))
            self.hourly_strip.update_data(result.hourly)
        # fetch 직후 응답 객체·임시 버퍼 정리
        QTimer.singleShot(500, _trim_memory)

    def _on_stocks(self, result):
        if isinstance(result, Exception):
            return
        for row, data in zip(self._stock_rows, result):
            row.update_data(data)

    # ── 종목 추가/삭제 ──────────────────────────────────────────────────────

    def _quick_add_stock(self):
        text, ok = QInputDialog.getText(
            self, "종목 추가",
            "Yahoo Finance 티커:\n예: AAPL, 005930.KS, 035720.KS",
        )
        if not ok or not text.strip():
            return
        ticker = text.strip().upper()
        if ticker in self.cfg["stocks"]:
            return
        self.cfg["stocks"].append(ticker)
        save_config(self.cfg)
        self._rebuild_stock_rows()
        self._refresh_stocks()

    def _remove_stock(self, ticker: str):
        if ticker in self.cfg["stocks"]:
            self.cfg["stocks"].remove(ticker)
            save_config(self.cfg)
            self._rebuild_stock_rows()
            self._refresh_stocks()

    # ── 설정 ─────────────────────────────────────────────────────────────────

    def _open_settings(self):
        self._show_border = True
        self.update()
        dlg = SettingsDialog(self.cfg, self.theme, self)
        if dlg.exec() != QDialog.Accepted:
            self._show_border = False
            self.update()
            return

        vals = dlg.values()
        _set_autostart(vals.pop("autostart", False))

        self.cfg = {**self.cfg, **vals}
        save_config(self.cfg)
        self._show_border = False
        self._apply_settings()

    def _apply_settings(self):
        """재시작 없이 설정 즉시 적용."""
        self.theme   = LIGHT if self.cfg.get("theme") == "light" else DARK
        self.scale_f = SCALE_FACTORS.get(self.cfg.get("scale", "M"), 1.0)

        self._update_stylesheet()

        s = lambda v: int(v * self.scale_f)
        new_w = self.cfg.get("width_px", s(520))
        if new_w < s(400):
            new_w = s(520)
        self.setMinimumWidth(s(260))
        self.setMaximumWidth(s(900))

        # UI 재구성
        self._stock_rows  = []
        self.clock_section = None
        self._build_ui()
        self.resize(new_w, self.height())

        # 핀 설정 반영 (플래그 변경 → 재show 필요)
        old_flags = self.windowFlags()
        self._update_window_flags()
        if self.windowFlags() != old_flags:
            self.show()

        pos = QPoint(self.cfg.get("pos_x", 100), self.cfg.get("pos_y", 100))
        self.move(pos)
        self._apply_native_effects()
        self.refresh_all()

    # ── 마우스 ───────────────────────────────────────────────────────────────

    _RESIZE_MARGIN = 12
    _SNAP_GRID     = 20
    _SNAP_EDGE     = 28

    def _edge_at(self, pos: QPoint) -> str:
        """가장자리 위치 반환: '', 'R', 'B', 'BR'."""
        r = pos.x() >= self.width()  - self._RESIZE_MARGIN
        b = pos.y() >= self.height() - self._RESIZE_MARGIN
        if r and b:
            return "BR"
        if r:
            return "R"
        if b:
            return "B"
        return ""

    @staticmethod
    def _cursor_for_edge(edge: str):
        return {
            "R":  Qt.SizeHorCursor,
            "B":  Qt.SizeVerCursor,
            "BR": Qt.SizeFDiagCursor,
        }.get(edge, Qt.ArrowCursor)

    def _snapped_pos(self, pos: QPoint) -> QPoint:
        """드래그 위치를 격자·화면 경계에 스냅."""
        screen = QApplication.screenAt(pos) or QApplication.primaryScreen()
        ag = screen.availableGeometry()
        x, y = pos.x(), pos.y()
        w, h = self.width(), self.height()
        se = self._SNAP_EDGE
        sg = self._SNAP_GRID

        # 화면 경계 흡착 (가장자리 se px 이내)
        snap_x = False
        if abs(x - ag.left()) < se:
            x, snap_x = ag.left(), True
        elif abs((x + w) - ag.right()) < se:
            x, snap_x = ag.right() - w, True

        snap_y = False
        if abs(y - ag.top()) < se:
            y, snap_y = ag.top(), True
        elif abs((y + h) - ag.bottom()) < se:
            y, snap_y = ag.bottom() - h, True

        # 경계 흡착이 없는 축만 격자 스냅
        if not snap_x:
            x = round(x / sg) * sg
        if not snap_y:
            y = round(y / sg) * sg

        return QPoint(x, y)

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            edge = self._edge_at(e.pos())
            if edge:
                self._resize_dir    = edge
                self._resize_start  = e.globalPos()
                self._resize_orig_w = self.width()
                self._resize_orig_h = self.height()
                self._drag_pos      = None
                self._show_border   = True
                self.update()
            else:
                self._drag_pos    = e.globalPos() - self.frameGeometry().topLeft()
                self._resize_dir  = ""
                self._show_border = True
                self.update()
        elif e.button() == Qt.RightButton:
            self._context_menu(e.globalPos())

    def mouseMoveEvent(self, e):
        if e.buttons() & Qt.LeftButton:
            if self._resize_dir and self._resize_start:
                dx = e.globalPos().x() - self._resize_start.x()
                dy = e.globalPos().y() - self._resize_start.y()
                s  = lambda v: int(v * self.scale_f)
                new_w = self.width()
                new_h = self.height()
                if "R" in self._resize_dir:
                    new_w = max(s(260), min(s(1400), self._resize_orig_w + dx))
                if "B" in self._resize_dir:
                    new_h = max(s(200), min(s(2000), self._resize_orig_h + dy))
                self.resize(new_w, new_h)
            elif self._drag_pos:
                raw = e.globalPos() - self._drag_pos
                self.move(self._snapped_pos(raw))
        else:
            edge = self._edge_at(e.pos())
            self.setCursor(self._cursor_for_edge(edge))

    def mouseReleaseEvent(self, e):
        if e.button() == Qt.LeftButton:
            if self._resize_dir:
                self.cfg["width_px"]  = self.width()
                self.cfg["height_px"] = self.height()
                p = self.pos()
                self.cfg["pos_x"], self.cfg["pos_y"] = p.x(), p.y()
                save_config(self.cfg)
                self._resize_dir   = ""
                self._resize_start = None
                self._show_border  = False
                self.update()
            elif self._drag_pos:
                p = self.pos()
                self.cfg["pos_x"], self.cfg["pos_y"] = p.x(), p.y()
                save_config(self.cfg)
                self._drag_pos    = None
                self._show_border = False
                self.update()

    def _context_menu(self, pos: QPoint):
        m = QMenu(self)
        m.setStyleSheet(_menu_qss(self.theme))
        m.addAction("새로고침").triggered.connect(self.refresh_all)
        m.addAction("종목 추가...").triggered.connect(self._quick_add_stock)
        m.addAction("설정...").triggered.connect(self._open_settings)
        m.addSeparator()
        m.addAction("종료").triggered.connect(QApplication.quit)
        m.exec_(pos)

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._apply_rounded_mask()

    def dragEnterEvent(self, e):
        # 새 파일 추가만 (타일 reorder 는 LauncherSection 이 직접 처리)
        if e.mimeData().hasUrls() and self.launcher_section is not None:
            e.acceptProposedAction()

    def dragMoveEvent(self, e):
        if e.mimeData().hasUrls() and self.launcher_section is not None:
            e.acceptProposedAction()

    def dropEvent(self, e):
        if self.launcher_section is None or not e.mimeData().hasUrls():
            return
        paths = [u.toLocalFile() for u in e.mimeData().urls() if u.isLocalFile()]
        self.launcher_section.add_paths(paths)
        e.acceptProposedAction()

    def paintEvent(self, _):
        """배경을 alpha=1로 채워 투명 영역도 마우스 이벤트를 수신하게 함.
        리사이즈·설정창 열릴 때는 추가로 테두리 표시."""
        p   = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        rad = int(20 * self.scale_f)
        rc  = QRectF(self.rect())

        # 클릭 수신용 최소 alpha (사람 눈에는 보이지 않음)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, 1))
        p.drawRoundedRect(rc, rad, rad)

        if not self._show_border:
            p.end()
            return

        is_dark = self.theme is DARK
        b_grad = QLinearGradient(rc.topLeft(), rc.bottomLeft())
        if is_dark:
            b_grad.setColorAt(0.0, QColor(255, 255, 255, 160))
            b_grad.setColorAt(1.0, QColor(255, 255, 255, 30))
        else:
            b_grad.setColorAt(0.0, QColor(255, 255, 255, 220))
            b_grad.setColorAt(0.5, QColor(200, 215, 240, 90))
            b_grad.setColorAt(1.0, QColor(180, 200, 230, 30))

        pen = QPen()
        pen.setBrush(b_grad)
        pen.setWidthF(1.5)
        p.setPen(pen)
        p.setBrush(Qt.NoBrush)
        p.drawRoundedRect(rc.adjusted(0.75, 0.75, -0.75, -0.75), rad, rad)
        p.end()

    def closeEvent(self, e):
        e.ignore()
        self.hide()




# ─── 진입점 ──────────────────────────────────────────────────────────────────

def _install_excepthook():
    import traceback

    def hook(exc_type, exc, tb):
        with open(LOG_PATH, "a", encoding="utf-8") as f:
            f.write("=" * 60 + "\n")
            traceback.print_exception(exc_type, exc, tb, file=f)
        sys.__excepthook__(exc_type, exc, tb)

    sys.excepthook = hook


def _check_single_instance() -> bool:
    """이미 실행 중이면 False 반환 (Windows named mutex 사용)."""
    if sys.platform != "win32":
        return True
    import ctypes
    _mutex = ctypes.windll.kernel32.CreateMutexW(None, True, "WeatherStockWidget_v1")
    if ctypes.windll.kernel32.GetLastError() == 183:  # ERROR_ALREADY_EXISTS
        return False
    return True


def main():
    if not _check_single_instance():
        sys.exit(0)

    _install_excepthook()
    import faulthandler
    fh = open(LOG_PATH, "a", encoding="utf-8")
    faulthandler.enable(file=fh, all_threads=True)
    sys.stderr = fh
    _log("===== 시작 =====")
    try:
        app = QApplication(sys.argv)
        app.setQuitOnLastWindowClosed(False)
        load_bundled_fonts()   # QApplication 생성 후
        ico = Path(__file__).parent / "widget.ico"
        if ico.exists():
            app.setWindowIcon(QIcon(str(ico)))
        w = MainWidget()
        screen = app.primaryScreen().availableGeometry()
        if not (0 <= w.x() <= screen.width() - 200 and 0 <= w.y() <= screen.height() - 200):
            w.move(screen.width() - w.width() - 60, 60)
        w.show()
        w._apply_native_effects()
        _log(f"show 완료, pos=({w.x()},{w.y()}), pinned={w.cfg.get('pinned')}, "
             f"theme={w.cfg.get('theme')}, scale={w.cfg.get('scale')}")
        sys.exit(app.exec_())
    except Exception as e:
        _log(f"main 예외: {e}")
        raise


if __name__ == "__main__":
    main()
