# M1-1 — Instagram Trend Analysis

**내 인스타그램 조회수 증가는 방문과 팔로우 증가로 이어졌을까?**

Instagram 계정 성과 CSV 6개로 일별 추이, 같은 날·다음 날 지표의 관계, 9월 급증 전후, 요일별 패턴을 분석하는 Python 프로젝트다. 데이터 139일을 보존하고, 공통 138일로 비교한다.

**분석 결과부터 읽기 → [REPORT.md](REPORT.md)**

![일별 주요 지표와 이동평균](images/01_daily_trends.png)

## 빠른 실행

Python **3.10 이상**이 필요하다. 실제 실행 검증 환경은 Python 3.12.14이다. 데이터가 포함되어 있어 실행할 때 API 키·Instagram 로그인·네트워크 수집은 필요 없다. 최초 라이브러리 설치에는 인터넷 연결이 필요하다.

프로젝트 폴더에서 실행한다.

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
python analysis.py
python -m unittest discover -s tests -v
```

Windows PowerShell에서는 가상환경 생성·활성화를 다음처럼 한다. 그 뒤 `pip install`, `analysis.py`, 테스트 명령은 같다.

```powershell
py -3 -m venv .venv
.venv\Scripts\Activate.ps1
```

정상 실행 메시지:

```text
OK: 139 calendar days; 138 complete comparison days.
Generated 4 PNG charts, processed tables and REPORT.md.
Original files in data/raw were read only.
```

그래프는 화면 창 없이 PNG로 저장된다. 그래프 안의 영문 표기는 별도 한글 폰트 설치 없이 재현하기 위한 선택이다. 본문과 그래프 해석은 한글이다.

`requirements.txt`는 직접 사용한 라이브러리 버전이다. 검증한 Python 3.12 환경 전체 버전은 [requirements-lock.txt](requirements-lock.txt)에 기록했다. 같은 Python 버전으로 환경 전체를 맞추려면 해당 파일로 설치한다. 다른 Python 버전에서는 직접 의존성 파일을 우선 사용한다.

## 데이터 흐름과 파일 구성

```text
data/raw/ 원본 6개
    → analysis.py: 형식 검증·날짜 결합·통계 계산
    → data/processed/: 정제 데이터·파생값·품질표·통계
    → images/: 그래프 4개
    → templates/REPORT.template.md + 계산값 → REPORT.md
```

```text
instagram-trend-analysis/
├── analysis.py
├── REPORT.md
├── README.md
├── DATA_SOURCE.md
├── requirements.txt
├── requirements-lock.txt
├── .gitignore
├── data/
│   ├── raw/                 # 제공받은 원본, 수정 금지
│   └── processed/           # 실행하면 재생성
├── images/                  # 실행하면 재생성, PNG 4개
├── templates/
│   └── REPORT.template.md   # 해석을 수정하는 원본 문서
└── tests/
    └── test_analysis.py
```

실행 시 `data/processed`, `images`의 결과와 `REPORT.md`를 갱신한다. 원본을 덮어쓰지 않는다. `REPORT.md` 본문을 직접 고치면 다음 실행 때 덮어써지므로, 문장 수정은 템플릿에서 한다.

## 분석 범위

| 질문 | 방법 | 그림 |
| --- | --- | --- |
| 성과 수준은 어떻게 변했는가? | 7일 이동평균, 첫/마지막 28일 및 월별 일평균 | `01_daily_trends.png` |
| 조회수와 방문·팔로우는 함께 움직이는가? | Pearson·순위 상관, 실제 날짜 기준 +1일 비교, 급증 제외·증감량 민감도 | `02_views_and_actions.png` |
| 급증 이후에도 높은 수준인가? | 9/23~24를 제외한 직전·직후 7일/14일 평균 | `03_event_windows.png` |
| 요일별 차이가 있는가? | 평균·중앙값·표본 수 | `04_weekday_patterns.png` |

- 전체 달력: 2026-05-29~2026-10-14, 139일.
- 주요 비교: 2026-05-29~2026-10-13, 138일.
- 10/14 팔로우는 기록이 없으므로 0으로 채우지 않는다.
- 팔로우는 계정의 전체 팔로워 잔액·순증가가 아니다.
- 시청자 지표를 날짜별로 더해 기간 전체 고유 인원으로 제시하지 않는다.
- 일별 비율은 사용자 전환율이 아니다. 상관관계와 최고점의 시차는 원인 증거가 아니다.
- 이 코드는 현재 자료를 위한 사례 분석이다. 새 기간을 넣으면 이벤트 기준 날짜와 템플릿의 해석·기간·행 수 설명도 함께 검토해야 한다.

## 정제 데이터 안내

| 파일 | 내용 |
| --- | --- |
| `daily.csv` | 날짜+지표 6개, 139행. 팔로우 한 칸은 결측 |
| `common.csv` | 모든 지표가 있는 138일 |
| `derived.csv` | 원지표, 과거 7일 평균, 일별 변화율(%), 높은 값 표시, 조회수 1,000회당 행동 지표 |
| `audit.csv` | 원본 행 수·기간·빈 값·0·IQR 표시 수·SHA-256 |
| `correlations.csv` | 대상 지표·시차·샘플 정의·쌍 수·상관계수 |
| `periods.csv` | 전후 7일/14일 구간과 평균·중앙값·합계 |
| `monthly.csv`, `weekday.csv` | 지표별 표본 수·집계값, 단일 헤더 |
| `summary.json` | 리포트 요약 수치. `daily_sum`은 날짜별 값의 산술합이며 시청자 고유 총수가 아님 |

각 CSV는 UTF-8 BOM을 사용해 Excel에서도 한글을 읽기 쉽도록 했다. 요일 인덱스는 월요일=0, 일요일=6이다. 평균·상관 등은 반올림 전 값으로 계산하고 CSV는 소수 8자리, 리포트는 읽기 쉬운 자리수로 표시한다.

## 검증

테스트는 다음 분석 오류를 방지한다.

- 실제 0과 빈 값의 혼동
- 중복 날짜, 음수·비정수·잘못된 숫자의 묵인
- 빠진 날짜의 자동 0 채우기
- 0으로 나누거나 결측을 직전 값으로 채운 변화율
- 다음 행을 다음 날로 오인하는 시차 연결
- 급증 제외 시 입력 날짜만 보고 결과 날짜를 놓치는 오류
- 전후 평균에 급증 이틀을 포함하는 오류

실행 결과와 직접 수행한 검증 내역은 [VALIDATION.md](VALIDATION.md)에 기록한다.

## GitHub 제출

저장소: [gaori2952/M1-1](https://github.com/gaori2952/M1-1) — 비공개.

저장소에서는 `REPORT.md`와 `images/`, `data/`의 상대 경로를 유지한다. 코드·원본·생성 결과·README·의존성 파일을 함께 올려야 링크와 재현이 모두 동작한다.

GitHub와 같은 이력에서 작업하려면 계정 인증 후 저장소를 복제한다.

```bash
git clone https://github.com/gaori2952/M1-1.git
cd M1-1
```

로컬 결과물 폴더에는 제작 과정의 별도 Git 이력을 보관했다. 배포용 ZIP에는 `.git` 이력을 포함하지 않는다. ZIP은 분석 실행에 바로 사용할 수 있으며, 이후 GitHub에 변경을 올릴 때는 위 복제본에서 작업한다.

이 프로젝트에는 개인 계정의 성과가 포함되어 있다. 공개 여부는 소유자가 결정하며, 과제 제출자가 접근해야 한다면 비공개 저장소의 읽기 권한도 함께 확인한다. 데이터 출처·수집 방법과 이용 범위는 [DATA_SOURCE.md](DATA_SOURCE.md)를 참고한다.

## 범위 밖의 확장

현재 제출물은 기본 과제에 집중한다. 대시보드·배포·예측은 보너스 후속 작업이다. 콘텐츠별 업로드 일시와 광고 집행 기록을 추가하면, 그래프의 급증 구간에 대한 해석을 보강할 수 있다.
