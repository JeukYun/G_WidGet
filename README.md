# G_WidGet

Windows 바탕화면에 상주하는 투명 글래스 위젯. 날씨 · 시계 · 시스템 · 주식 · 앱 런처를 한 화면에 모아서 보여줍니다.

![Version](https://img.shields.io/badge/version-0.5-blue)
![Python](https://img.shields.io/badge/Python-3.8%2B-blue)
![PyQt5](https://img.shields.io/badge/PyQt5-5.15%2B-green)
![Platform](https://img.shields.io/badge/Platform-Windows%2011-lightgrey)

---

## 기능

- **시계** — 날짜 + 시각, 12/24시간 형식 선택
- **날씨** — wttr.in 기반 현재 기온·체감·습도·풍속 + 5칸 시간별 예보 (30분 자동 갱신)
- **시스템** — CPU 사용률, RAM 사용량(GB + %), CPU 온도(°C, 80°C↑ 빨간색 경고)
- **주식** — Yahoo Finance 기반 종목 시세·등락률 (KS/US 모두 지원)
- **앱 런처** — `.lnk`/`.exe` 드래그 등록, 클릭 한 번으로 실행
- **투명 글래스** — DWM acrylic / 완전 투명 모드, 벽지가 그대로 비침
- **바탕화면 고정** — Progman 자식 부착으로 Show Desktop / Win+D / Task View 영향 없음
- **스냅 이동** — 드래그 시 격자 + 화면 경계 자동 흡착
- **자동 시작** — 레지스트리 등록으로 부팅 시 자동 실행
- **작업표시줄 투명화** — 토글 옵션
- **테마/스케일** — 라이트·다크 / S·M·L·XL, 재시작 없이 즉시 적용

## 설치

```bash
git clone https://github.com/JeukYun/G_WidGet.git
cd G_WidGet
pip install -r requirements.txt
```

### 폰트 (선택)

`fonts/` 에 [Pretendard Variable](https://github.com/orioncactus/pretendard) (`PretendardVariable.ttf`) 가 포함돼 있습니다. 없으면 Segoe UI 로 자동 대체됩니다.

## 실행

```bash
# 콘솔 없이 백그라운드 실행
pythonw widget.py

# 또는 한 번 실행으로 아이콘 + 바로가기 생성
python install.py
```

`install.py` 가 만들어 주는 항목:

- `widget.ico` — 다중 해상도 ICO (16~256)
- `Widget.lnk` — 더블클릭 실행용 바로가기 (콘솔 없음)
- `Widget.exe` — `pythonw.exe` 사본 (작업관리자에 'Widget' 으로 표시되도록)

바로가기는 바탕화면·시작메뉴·작업표시줄 어디로 끌어놓아도 됩니다. 이름도 자유롭게 변경 가능.

### 작업관리자 표시 이름 커스터마이즈 (선택)

`Widget.exe` 의 아이콘과 FileDescription 까지 임베드하려면:

```bash
python embed_icon.py
```

## 설정

트레이 아이콘 우클릭 → **설정** 또는 위젯 우클릭 → **설정**

| 항목 | 설명 |
|------|------|
| 도시 | 날씨 조회 도시 (영문) |
| 종목 | 주식 티커 (콤마 구분, 예: `005930.KS, AAPL, TSLA`) |
| 크기 | S / M / L / XL |
| 테마 | 라이트 / 다크 |
| 표시 위치 | 바탕화면 고정 / 항상 위에 |
| 시계 | 표시 여부, 12/24시간 형식 |
| 주식 패널 | 표시 / 숨김 |
| 앱 런처 | 표시 / 숨김 |
| 자동 시작 | 부팅 시 자동 실행 등록 |
| 작업표시줄 투명 | 작업표시줄 알파 투명화 |

설정은 `config.json` 에 저장되며 적용 시 재시작 없이 즉시 반영됩니다.

## 구조

```
├── widget.py        # 메인 위젯 (UI, 설정, 트레이, Win32 hooks)
├── fetcher.py       # 날씨·주식 데이터 fetch
├── icons.py         # PIL 기반 날씨 아이콘 렌더링
├── install.py       # widget.ico + Widget.lnk + Widget.exe 생성
├── embed_icon.py    # Widget.exe 에 아이콘/버전 정보 임베드 (선택)
├── fonts/           # Pretendard Variable
├── requirements.txt
└── .gitignore
```

## 의존성

| 라이브러리 | 용도 |
|-----------|------|
| PyQt5 | UI 프레임워크 |
| requests | 날씨/주식 API |
| Pillow | 날씨 아이콘 렌더링 |
| psutil | CPU/RAM 모니터링 |
| wmi (Windows) | CPU 온도 읽기 |
| pywin32 (선택) | `embed_icon.py` 사용 시 |

## 변경 이력

### v0.5 (2026-05)
- 주식 패널 추가 (Yahoo Finance)
- 앱 런처 패널 추가 (.lnk/.exe 등록)
- 작업표시줄 투명화 토글
- Progman 자식 부착으로 진짜 바탕화면 위젯처럼 동작
- 완전 투명 / Acrylic 자동 전환
- 다크 테마 보강, S~XL 스케일

### v0.1
- 초기 버전: 시계 · 날씨 · 시스템 모니터

## 로드맵

- [ ] 주식 패널 별도 창 분리 옵션
- [ ] 위젯 종류별 자유 배치 (그리드)
- [ ] CPU 코어별 온도 (LibreHardwareMonitor 연동)
- [ ] 멀티 모니터 좌표 자동 보정
