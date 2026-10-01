# 20일 거래량 3배 스캐너

미국 상장 **주식(ETF 제외)** 중 아래 두 조건을 동시에 만족하는 종목을 매일 자동으로 찾는 GitHub Pages 프로젝트입니다.

1. 최근 20거래일 평균 거래량 ÷ 그 이전 20거래일 평균 거래량 ≥ **3.0배**
2. 최근 20거래일 주가 등락률 < **+3.0%**

하락 종목도 포함하며 웹페이지에서 **🔻 하락**으로 별도 표시합니다.

## 구조

- `scanner.py` — 미국 상장 종목 목록을 받고, 일봉 데이터로 조건 계산
- `.github/workflows/scan.yml` — 평일 장 마감 후 자동 실행 + 수동 실행
- `data/results.json` / `data/results.csv` — 스캔 결과
- `index.html` — GitHub Pages 화면

## 가장 쉬운 설치

1. GitHub에서 새 repository를 하나 만듭니다. 예: `volume-surge-scanner`
2. 이 폴더의 파일을 repository 루트에 전부 업로드합니다.
3. **Actions** 탭 → `Daily volume scanner` → **Run workflow**를 한 번 실행합니다.
4. 완료 후 `data/results.json`에 실제 결과가 저장됐는지 확인합니다.
5. repository의 **Settings → Pages**에서 `Deploy from a branch`를 선택하고 `main / (root)`를 지정합니다.
6. 잠시 후 GitHub Pages 주소로 접속하면 됩니다.

## 자동 업데이트

GitHub Actions가 평일 **23:00 UTC**에 자동 실행됩니다.
- 미국 서머타임: 오후 7시 ET
- 미국 표준시: 오후 6시 ET

따라서 정규장 종료 이후 데이터를 기준으로 결과가 갱신됩니다.

## 계산 정의

거래량 배수:

```text
최근 20거래일 평균 Volume / 그 이전 20거래일 평균 Volume
```

20일 가격 등락률:

```text
(최근 종가 / 20거래일 전 종가 - 1) × 100
```

조건은 `scanner.py` 상단에서 쉽게 변경할 수 있습니다.

```python
RECENT_DAYS = 20
PREVIOUS_DAYS = 20
VOLUME_MULTIPLE_MIN = 3.0
PRICE_CHANGE_MAX_PCT = 3.0
```

## 참고

가격 데이터 제공처의 일시적인 요청 제한이나 상장 직후 종목처럼 40거래일 이상 데이터가 없는 종목은 `data_failure_count`에 포함될 수 있습니다. 다음 자동 실행 때 다시 시도합니다.

이 스캐너는 종목 후보를 찾는 도구이며 매수/매도 신호를 보장하지 않습니다.
