# KBO Predict — 설계 문서

- 작성일: 2026-10-27
- 상태: 빌더 검토 반영 완료, 사용자 승인 대기
- 관련 문서: `docs/research/kbo-data-sources.md` (데이터 소스 조사), `DESIGN_clay.md` (디자인 시스템), `.superpowers/brainstorm/860-1793099185/content/clay-hybrid.html` (확정 목업)

---

## 1. 의도와 이유

개인 포트폴리오용 미니프로젝트. 채용 담당자가 **세 군데**에서 같은 결과를 확인할 수 있어야 한다.

1. **웹사이트** — 오늘 KBO 경기의 승률 예측과 선수 유형 지도를 예쁘게 보여준다.
2. **GitHub 저장소** — 매일 GitHub Actions가 모델을 실행해 결과 JSON을 커밋한 기록(Actions 로그, bot 커밋)이 남아 있어 "진짜 돌아간다"를 증명한다.
3. **Jupyter 노트북** — 같은 과정을 친절한 설명과 함께 셀 단위로 읽을 수 있고, `.py` 실행 결과와 숫자가 정확히 일치한다.

주제는 두 모델의 조합이다.

- **경기 승패 예측** (이진 분류): 오늘 경기에서 홈팀이 이길 확률.
- **선수 유형 클러스터링** (비지도): 시즌 스탯만으로 타자·투수를 몇 가지 유형으로 묶고, 그 유형을 승패 모델의 피처(타선-투수 상성)로도 쓴다.

지금(2026-10-27)은 한국시리즈가 진행 중이다. 정규시즌으로 학습한 모델이 남은 포스트시즌 경기를 **실시간으로** 예측하는 것이 첫 라이브 목표이고, 시즌이 끝나면 2026 시즌 되감기 모드로 전환해 2027년 4월 개막까지 사이트가 살아 있게 한다.

## 2. 목표 / 비목표 / 반(反)목표

### 목표
- 정규시즌 백테스트 적중률이 단순 베이스라인(홈팀 승 / 승률 높은 팀 승 / 선발 ERA 낮은 팀 승)보다 **통계적으로 유의하게** 높을 것. 야구 승패 예측의 현실적 상한은 60% 초반이므로, 목표치는 "베이스라인 +3%p 이상"이지 "70%"가 아니다.
- 캘리브레이션이 좋을 것 (모델이 70%라고 한 경기들의 실제 승률이 65~75% 안).
- 매일 자동 실행이 **사람 손 없이** 한 달 이상 이어질 것.
- `.py` 파이프라인과 `.ipynb`가 **같은 숫자**를 내고, 이를 자동 검증할 것.
- 웹사이트가 `DESIGN_clay.md` 시스템을 지키고, 확정 목업과 같은 구조일 것.

### 비목표
- 실시간(이닝 단위) 예측, 베팅용 배당 비교.
- 타석 단위 예측 (공개 데이터 없음 — 조사 결과).
- 사용자 로그인, 댓글 등 서비스 기능.
- 모델 API 서버 상시 운영 (배치 결과 파일로 충분).

### 반목표 (기술적으로 되더라도 실패인 것)
- KBO 공식 사이트(koreabaseball.com)를 직접 크롤링하는 것. 약관에 크롤링 금지·법적 조치가 명문화돼 있다. 공개 포트폴리오에 이 흔적이 있으면 감점 요인이다.
- 경기 **후** 정보가 피처에 섞여 적중률이 부풀려지는 것 (누수). 채용 담당자가 코드를 보면 바로 드러난다.
- 노트북과 `.py`가 "대충 비슷한" 결과를 내는 것. 소수점까지 같아야 한다.
- 디자인이 기본 템플릿처럼 보이는 것 (회색 카드 + 파란 버튼).

## 3. 제약

| 항목 | 내용 |
|---|---|
| 도구 | 계획·모델·파이프라인: Claude Code(Max) + Codex(Plus). 웹: Genspark(5,000 크레딧). |
| 배포 | 코드·데이터·Actions: 사용자의 GitHub("민서" 계정, public 저장소). 웹: Genspark 배포. |
| 데이터 | 아래 4절. KBO 공식 사이트 직접 수집 금지. |
| 시기 | 2026-10-27 한국시리즈 진행 중. 포스트시즌 종료 후 ~2027-03까지 비시즌. |
| 비용 | GitHub Actions 무료 한도(월 2,000분) 안. 하루 1~2분 × 2회 + 주 1회 재학습 10분이면 충분. |
| 언어 | 사이트·노트북·README 모두 한국어. 코드 식별자·주석은 영어/한국어 혼용 가능하되 노트북 설명은 한국어. |

## 4. 데이터

조사 결과(`docs/research/kbo-data-sources.md`)에 따라 다음으로 확정한다.

### 4.1 소스

**2026-10-27 변경: 네이버 스포츠 API → MyKBOStats.** 네이버 `api-gw.sports.naver.com`은 curl(브라우저형 TLS)에는 응답하지만 Python `requests`/`urllib`/raw SSL에는 응답하지 않고(이 PC와 GitHub Actions ubuntu 러너 모두에서 확인, probe 워크플로 실행 #1), `python-requests` UA도 차단한다 — 봇 클라이언트를 TLS 지문·UA 수준에서 걸러내는 것으로 판단. 지문 위조로 우회하는 것은 이 프로젝트의 반목표(공개 포트폴리오에 차단 우회 코드)이므로 하지 않는다.

| 용도 | 소스 | 비고 |
|---|---|---|
| 경기 일정·결과·상태·구장·시간 | **MyKBOStats** `https://mykbostats.com/schedule/week_of/YYYY-MM-DD` (주간 HTML, 화요일 시작) | 로그인 불필요, robots.txt `Crawl-delay: 5` 준수. 게임 라인에 `game-line-{id}`, `data-game-datetime`(UTC), 팀명, 점수, 상태(`Final`/`Live`/`Canceled …`/시간+구장). |
| 경기 박스스코어 (타자·투수, 선수 ID) | MyKBOStats `/games/{id}-{Away}-vs-{Home}-{YYYYMMDD}` | 타자: Pos, BA, AB, R, H, HR, RBI, BB, SO, HBP. 투수: ERA, IP(`4 ⅓`), NP, R, ER, H, HR, SO, BB, HB, GS(게임스코어). 선수 링크 `/players/{id}-…`. 첫 행 = 선발. |
| **경기 전 예상 선발투수** | ~~현재 없음.~~ **2026-10-29 확보**: MyKBOStats 예정 경기 페이지(`/games/{id}-…`)의 "Starting pitchers" 섹션 (0단계 당시 확인한 페이지에는 "Scheduled"·전적·구장·중계만 있었다). | v0.1은 선발 피처 없이 갔다. 2단계부터 라이브 추론에 사용 → `data/raw/{season}/starters.jsonl` (5.1, 13절 2단계 규칙). |
| 2001~2009 경기 결과 (선택) | `dentearl/kbo-data` 정적 JSON | 우선순위 낮음. |

추가 확인(2026-10-27): 네이버 클라우드 **NAVER API HUB**는 검색 API(뉴스·블로그 등)와 Data Lab(쇼핑 인사이트·검색어 트렌드)만 제공하며 스포츠/KBO API는 없다 (guide.ncloud-docs.com/docs/apihub-use). KBO 공식 공개 API도 없음. 상용(Sportradar 등)은 유료라 제외.

### 4.2 선수 시즌 스탯은 박스스코어 집계로 만든다 (내 결정)

MyKBOStats 박스스코어의 선수 ID(`/players/{id}`)를 키로 **경기별 박스스코어를 시즌 단위로 합산**하면 타자(AB, H, HR, BB, K, HBP)·투수(IP, R, ER, H, HR, K, BB, HBP, NP) 시즌 스탯이 나온다. 소스가 하나라서 선수명 조인 문제가 없고, "경기 날짜 기준 누적"이 자연스러워 누수 방지가 쉽다.

박스스코어에 2B/3B/SB가 없다 → 클러스터링(5.2)의 ISO·주루 지표는 선수 페이지(`/players/{id}`)의 시즌 행이나 경기 페이지 하단 "2B/3B/SB" 요약 텍스트에서 보완한다 (3단계에서 결정). **→ 확정 (2026-10-29): 경기 페이지 하단 기록표**(`data-game-section="records"`, `이름 (1st, 9th inning)` 형식, 이닝 수 = 개수). 선수 페이지는 선수당 1요청 × 수천 명이라 5초 간격으로 며칠이 걸려 제외했다. 로컬 HTML 캐시로 9,362경기를 재파싱해 박스스코어 타자 행에 `doubles`·`triples`·`sb`를 보탰고(기존 칸 불변, `features.parquet` SHA256 동일), 캐시 없는 18경기는 새 칸이 None이다. 덤으로 같은 기록표의 한글 `title` 속성(`2루타: 신종길(1회) 필(1회)`)에서 선수 한글 이름(`names_ko`)을 얻었다(시즌별 투표 — 개명 선수는 최근 시즌 이름, 1,604명, 개명 별칭 31명은 `data/raw/name_aliases.json`). 매칭 규칙은 13절 3단계 규칙.

저장 방식(내 결정): 주간 일정은 파싱한 행을 `data/raw/{season}/games.jsonl`, 박스스코어는 파싱한 JSON을 월별 파일 `data/raw/{season}/boxscores/{YYYY-MM}.jsonl.gz`로 커밋한다(시즌 단위 단일 파일은 매일 통째로 재커밋되어 저장소가 커지므로 월별로 나눴다 — 지난달 파일은 더 이상 바뀌지 않는다). 원본 HTML(경기당 ~150KB)은 git에 넣지 않고 로컬 캐시 `data/cache/html/`(gitignore)에만 둔다 — 파서는 버전 관리되고 MyKBOStats가 과거 페이지를 유지하므로 재현 가능하다.

### 4.3 범위

- **학습 기간: 2015~2026 정규시즌** (내 결정). 2015년 kt 위즈 합류 후 10구단 체제라 리그 구조가 같다. MyKBOStats는 2014년부터 있지만 2014는 9구단이라 홈/원정 구조가 다르고, 12년치면 약 8,600경기로 충분하다.
- 포스트시즌 경기는 학습에 넣지 않고(선발 운용이 다름) 예측 대상으로만 쓴다. "포스트시즌 보정"은 1차 버전에선 **표시용 주석**이지 모델 항이 아니다 — 데이터가 너무 적다.
- 우천 취소·서스펜디드 경기는 결과 확정 시점에만 반영.

### 4.4 수집 규칙

- 요청 간 **5초** `sleep`(robots.txt Crawl-delay), UA `Mozilla/5.0 (compatible; kbo-predict/0.1; +https://github.com/kimminseo2323-prog/2610_KBO_predict)`, 실패 시 1회 재시도 후 중단 (차단 유발 방지).
- 백필(시즌당 주간 페이지 ~30 + 경기 ~720 ≈ 750요청 × 5초 ≈ 1시간/시즌)은 **로컬에서** 실행해 커밋한다. Actions는 증분(최근 1~2주)만 수집한다. 2015~2025 백필은 1단계에서 시즌별로 나눠 진행.
- 파싱 결과를 커밋하고 HTML은 로컬 캐시에만 둔다 (4.2). 가공은 별도(`data/processed/*.parquet`). 커밋된 파싱 결과가 노트북·py 동일성 검증의 입력이다.

## 5. 모델

### 5.1 승패 예측

- **문제 정의**: 경기 전날 밤 시점의 정보만으로 `P(홈팀 승)`. 무승부(KBO 정규시즌 12회 연장 후 무승부 가능)는 학습에서 제외하고, 예측 시엔 그냥 확률만 낸다.
- **피처** (전부 "해당 경기 이전" 데이터로만 계산):
  - 선발투수 (**경기 전 예상 선발 소스가 확보된 뒤 — 2단계**): 시즌 누적 ERA·FIP 근사(K, BB, HR 기반)·K/9·BB/9, 최근 3경기 평균 실점, 당해 시즌 이닝 수(표본 크기), 상대팀 상대 성적. v0.1은 선발 피처 없이 팀 승률·최근 10경기·득실차·홈으로만 간다. **소스: MyKBOStats 예정 경기 페이지의 "Starting pitchers" 섹션을 확보(2026-10-29)** — 0단계의 "선발 소스 부재" 결론은 이것으로 대체된다. 학습·평가는 박스스코어의 실제 선발(투수 순서 1), 라이브는 이 예고 선발을 쓴다(13절 2단계 규칙).
  - 팀: 시즌 승률, 최근 10경기 승률, 피타고리안 승률(득실점), 팀 OPS·팀 ERA 누적, 홈/원정 승률. (구현 시 확정: OPS는 근사 OBP+HR/PA+K%+BB%로 대체, 구장·요일 제외 → 13절)
  - 경기: 홈/원정, 구장, 요일, 맞대결 최근 전적.
  - **유형 상성**: 상대 선발의 유형(5.2 결과) × 자팀 타선의 유형 구성 비율. 이 피처는 "넣기 전/후"를 모델 성적표에 둘 다 보여준다.
- **알고리즘**: 로지스틱 회귀(해석용 베이스라인) + **LightGBM**(메인). 둘 다 보고서에 남기고 사이트는 더 나은 쪽을 쓴다. SHAP으로 경기별 요인 분해(사이트 "승률을 가른 요인" 카드).
- **검증**: 시즌 단위 시계열 분할. 2015~2024 학습 → 2025 검증 → 2026 테스트. 지표: 정확도, log loss, Brier, 캘리브레이션 곡선. 베이스라인 3종과 같은 표에 비교.
- **캘리브레이션**: LightGBM 출력에 isotonic 또는 Platt 보정 적용 여부를 검증 세트에서 결정.
- **재학습**: 매주 월요일 Actions에서 전체 재학습 → `models/win_model.pkl` 갱신. 매일 실행은 추론만.
- **모델 두 벌 (내 결정, 누수 방지)**:
  - `report` 모델: 2015~2024 학습, 2025 검증, **2026은 완전 홀드아웃**. 이 모델로 `model_report.json`과 `rewind/2026/*.json`을 **한 번 생성해 고정**한다 (`model_version: "report-2026"`). 주간 재학습이 이 파일들을 덮어쓰지 않는다. 성적표의 2026 적중률은 학습·선택에 쓰지 않은 시즌의 값이다(13절 2단계 규칙의 주의 참고).
  - `live` 모델: 가용한 전체 정규시즌(2015~2026)으로 학습. 포스트시즌·2027 라이브 추론에만 쓴다. 라이브 적중률은 `history.csv`에 예측 시각과 함께 쌓이므로 그 자체가 out-of-sample 기록이다.
  - 2027 시즌이 끝나면 `report` 모델을 "2016~2025 학습, 2026 검증, 2027 홀드아웃"으로 한 번 옮긴다. 사이트 성적표에 "어느 모델, 어느 기간" 표기 필수.

### 5.2 선수 유형 클러스터링

- **대상**: 시즌별 타자(규정 타석 미달 포함, **200 PA 이상**), 투수(**50 IP 이상** 또는 구원 **30경기 이상**). 임계값은 내 결정이며 빌더가 분포 보고 조정 가능. (구현 시 확정: 값 그대로, 정규시즌 FINAL만 집계 → 타자 1,327 / 투수 1,591 선수-시즌 → 13절)
- **피처**: 비율 지표만 (K%, BB%, ISO, BABIP, GB 추정 불가 시 제외, SB 비율, HR/FB 근사 등). 표준화 후 사용. 누적 스탯(홈런 개수 등)은 출전 수에 끌려가므로 제외. (구현 시 확정: 타자 `k_pct, bb_pct, hr_pct, iso, babip, sb_rate`, 투수 `k_pct, bb_pct, hr_pct, babip, start_share`. GB·HR/FB는 FB 기록이 없어 제외 → 13절)
- **알고리즘**: K-means (K=4~7 탐색, 실루엣 + 연도 간 유형 유지율로 선택) → 2D 시각화는 UMAP(결정론적 seed) 또는 PCA. GMM은 "소속 확률"을 주므로 K-means 결과와 비교해 더 설명 잘 되는 쪽 채택. (구현 시 확정: `score = 실루엣 + 유지율` 최대 K → 타자·투수 모두 K=4. 2D는 PCA. 라벨은 K-means로 고정하고 소속 확률은 GMM 일치율이 0.95 미만이라 두 그룹 모두 중심 거리 소프트맥스 → 13절)
- **유형 이름**: 클러스터 중심의 스탯 프로파일을 보고 사람이 붙인다 (예: 파워형·컨택형·출루형·공수겸장·수비형). 이름은 `config/cluster_labels.yaml`에 두고 코드에서 분리. (구현 시 확정: 타자 파워형·장타 지향형·컨택형·주루형, 투수 선발형·스윙맨형·제구 불안 불펜형·삼진 불펜형. 수비 지표가 없어 공수겸장·수비형은 만들 수 없음)
- **유사 선수**: 같은 표준화 공간에서 코사인 유사도 상위 5명 (연도 무관). (구현 시 확정: 같은 그룹 안, 같은 선수의 다른 시즌 제외 → 13절)
- **승패 모델과의 연결**: 경기 날짜 기준으로는 "직전 시즌 유형"을 쓴다 (당해 시즌 유형은 시즌 중반까지 불안정하고 누수 위험). (구현 시 확정: 상성 피처 9개, 중심은 2015~2025로만 맞춤, 전후 비교 결과 `adopt: false`로 라이브 미반영 → 13절, 12절 3)

### 5.3 재현성

- 모든 난수 seed 고정(`config/settings.yaml`의 `seed: 42`), LightGBM `deterministic=True`, `num_threads=1`로 학습.
- 데이터 스냅샷: 학습에 쓴 `data/processed/*.parquet`의 SHA256을 `models/manifest.json`에 기록.

## 6. `.py` ↔ `.ipynb` 동일성 (사용자 필수 요구)

구조 원칙: **로직은 `src/`에 한 번만 쓰고, `.py` 스크립트와 노트북은 둘 다 그 함수를 호출한다.** 노트북에 로직을 복붙하지 않는다.

```
src/kbo_predict/
  mykbo_client.py # MyKBOStats HTTP (5초 간격, 캐시)
  mykbo_parse.py  # 주간 일정·박스스코어 HTML 파서
  collect.py      # 기간 수집 CLI
  features.py     # 피처 생성 (날짜 기준 누적)
  train_win.py    # 승패 모델 학습
  cluster.py      # 유형 클러스터링
  predict.py      # 오늘 경기 추론 → JSON
  publish.py      # 사이트용 JSON/CSV 생성
  simulate.py     # 가을야구·시리즈 몬테카를로 → outlook (4단계)
  rewind.py       # 날짜별 되감기 JSON (4단계)
scripts/
  run_pipeline.py # 전체 파이프라인 (Actions가 호출)
  build_rewind.py # 되감기 JSON 생성 CLI (4단계)
  check_parity.py # 커밋된 산출물 vs 다시 만든 산출물 + 노트북 실행 (4단계 확정, 아래)
notebooks/
  01_데이터_수집과_살펴보기.ipynb
  02_피처_만들기.ipynb
  03_승패_예측_모델.ipynb
  04_선수_유형_클러스터링.ipynb
  05_오늘_경기_예측.ipynb
```

검증 방법 (`scripts/check_parity.py`):
1. `run_pipeline.py`를 실행해 `artifacts/py/` 에 결과(피처 parquet, 모델 지표 JSON, 예측 JSON, 클러스터 라벨 CSV)를 저장.
2. 노트북 5개를 `papermill` 또는 `nbconvert --execute`로 순서대로 실행해 `artifacts/nb/` 에 같은 파일을 저장.
3. 파일별로 비교: parquet/CSV는 `pandas.testing.assert_frame_equal`(float은 `rtol=1e-9`), JSON은 정렬 후 SHA256 일치.
4. 불일치 시 어떤 파일·어떤 컬럼이 다른지 출력하고 비정상 종료.
5. 이 스크립트는 **GitHub Actions의 PR 체크**와 주간 재학습 잡에서 둘 다 돌린다. README에 "parity: passing" 배지.

**→ 4단계 확정 (2026-10-29)**: 위 1~3의 "artifacts/py vs artifacts/nb"를 **"커밋된 산출물 vs 저장소의 원본 데이터와 코드만으로 다시 만든 산출물 + 노트북 내부 assert"**로 구체화했다. 노트북 02~05는 각자 마지막 셀에서 매니페스트 지문·보고서·사이트 JSON과 비교하는 assert를 갖고 있으므로, 노트북 산출물을 따로 저장해 비교하지 않고 실행 성공(오류 출력 0)을 검사한다. `papermill` 대신 `nbclient`(테스트와 같은 방법). 네트워크 요청 0회, 재생성본은 `--out`(기본 `artifacts/parity/`, gitignore)에만 쓰고 `data/public`·`models` 아래 출력은 거부한다.

| 항목 | 다시 만드는 것 | 비교 기준 | 허용 오차 |
|---|---|---|---|
| (1) 피처 | `features.parquet`, `matchup.parquet` (얼린 시즌 2015~2026) | `models/manifest.json`의 `features_fingerprint`(report·team), `report.matchup_fingerprint` | 값 지문 일치. 파일 SHA256(`features_sha256`·`matchup_sha256`)은 플랫폼 의존이라 정보 행으로만. 커밋 당시와 같은 바이트의 parquet가 로컬에 있으면 `assert_frame_equal(rtol=1e-9, atol=0)`도 |
| (1) 군집 | 선수 유형 CSV, 군집 묶음 재적합 | `clusters.types_sha256`, 커밋된 `models/clusters.pkl` | CSV SHA256 일치(이미 소수 6자리 텍스트), `cluster compare`: 중심 `allclose(rtol=0, atol=1e-9)` · 맞춤 시즌 라벨 동일 |
| (2) 보고서 | `train_report`, `train_team` 요약 | `model_report.json`(`generated_at`·`commit_sha`·`run_url`·`features_sha256` 제외), 그 안의 `ablation.no_starter` | 실수 상대 오차 1e-9 (`abs_tol=0`), 나머지 값은 정확히 |
| (2) 모델 예측 | report-2026·team-2026 번들 재학습, 라이브는 조건부(아래) | 커밋된 pkl의 `predict_proba` (8,465행) | `atol 1e-9`. pkl 바이트는 `trained_at` 때문에 비교하지 않는다 |
| (3) 사이트 JSON | `players.json`, `teams.json` (`cluster publish`와 같은 함수) | 커밋본 (`generated_at`·`commit_sha` 제외) | 정확히 같음 |
| (4) 되감기 | 2026 시즌 전체 (`rewind.build_season`) | `data/public/rewind/2026/`의 165일 파일 + `index.json` = 166개, 파일 목록 포함 (`generated_at`·`commit_sha` 제외) | 정확히 같음 |
| (5) 노트북 | 02~05 실행 | 노트북 안의 assert | 오류 출력 0. 02~05 모두 필수(없으면 실패). 노트북 03·04의 assert도 (1)(2)와 같은 규칙(`kbo_predict.parity`: 값 지문, 보고서 실수 상대 1e-9, 예측 `atol 1e-9`)이라 Linux에서도 통과한다. `--quick`이면 (5)를 건너뛴다 |

- **값 지문**: `features.features_fingerprint(df)` = 실수 열을 `round(6) + 0.0`(−0.0 정리)한 뒤 `to_csv(index=False, lineterminator="\n", float_format="%.6f")`의 SHA256. `train_win`·`model_report.json`·`models/manifest.json`이 함께 기록한다. 현재 값: 피처 `752b4319…`, 상성 `3419c8c1…`.
- **얼린 시즌과 라이브**: report-2026·team-2026·clusters-2026과 그 하류는 `kbo_predict.FROZEN_SEASONS`(2015~2026)만으로 다시 만든다 → 2027 경기가 쌓여도 비교가 깨지지 않는다. 라이브 `win_model.pkl`은 manifest의 `live.features_fingerprint`가 지금 있는 시즌 전부로 만든 parquet의 지문과 같을 때만 다시 학습해 비교하고(비교 행 = 커밋된 라이브 번들의 `seasons`), 다르면 "건너뜀"이다. `--require-live`면 건너뜀도 실패다.
- **입력 규칙**: 군집이 들어가는 하류(상성 parquet, `cluster_quality`, 사이트 JSON, 되감기 선발 유형)는 커밋된 `models/clusters.pkl`로 만들고, 군집을 다시 맞출 수 있는지는 (1)이 따로 본다 — BLAS 차이 하나가 여러 줄에 중복 보고되지 않게.
- **출력**: 항목별 표(커밋본 · 재생성 · 결과)와 단계별 시간. 하나라도 다르면 첫 번째로 다른 파일·키 경로를 찍고 exit 1.
- **명령과 시간**(Windows): `python -X utf8 scripts/check_parity.py --quick` 약 37초(ci), 노트북 포함 전체 약 100초(주간 재학습 — `--require-live`와 함께, Linux에서 노트북까지). Linux ci(ubuntu, OpenBLAS)에서도 `--quick` 통과(실행 40882643905). `--repo` 기본값은 스크립트가 있는 저장소 루트(작업 폴더와 무관).

노트북 작성 규칙:
- 각 노트북 맨 위에 "이 노트북이 하는 일 / 왜 필요한지 / 어떤 `.py`와 짝인지" 마크다운 셀.
- 코드 셀마다 바로 위에 한국어 마크다운 설명: 무엇을, 왜, 결과를 어떻게 읽는지. 야구 용어(ERA, OPS, ISO 등)는 처음 나올 때 한 줄 설명.
- 중간 결과를 `display()`로 보여주고, 숫자가 뜻하는 바를 한 줄로 해석.
- 노트북은 실행 결과 포함 상태로 커밋 (GitHub에서 바로 읽히게).

## 7. 자동화 (GitHub Actions)

| 워크플로 | 트리거 | 하는 일 | 산출물 |
|---|---|---|---|
| `daily.yml` | cron 매일 **KST 09:07**(UTC `7 0 * * *`) + `workflow_dispatch` | `run_pipeline.py`: 대상일 −7~+14일 일정·박스스코어 수집 → `history.csv` 적중 기록 갱신 → 오늘 경기가 있으면 예고 선발 수집(없으면 요청 생략) → 수집 창(−7일) 이전인데 박스스코어 없는 정규시즌 FINAL 재수집(최신순 20개, 별도 try — 얼린 시즌 2015~2026과 수집이 예외로 멈춘 실행은 건너뜀) → 라이브 v0.2 추론 + `outlook`(팀 모델 `team-2026`, 시리즈의 오늘 경기만 v0.2 선발 포함 확률) → `latest.json`(경기 있는 날만), `status.json`(매일) | bot 커밋 `auto: predictions YYYY-MM-DD-HHMM` (`data/raw`, `data/public`), 수집 실패 시 `collect-failure` 이슈 |
| `daily.yml` 2차 | cron **KST 17:07**(UTC `7 8 * * *`) | 같은 실행 — 선발투수 변경 반영해 재추론 (KBO는 당일 오후 선발 확정이 흔함) | 같은 파일 갱신 |
| `weekly_retrain.yml` | 매주 월요일 **KST 03:07**(UTC 일요일 `7 18 * * 0`) + `workflow_dispatch` | 피처 재생성 → `train_win live --skip-if-same`(피처 parquet 전 행의 예측이 기존 pkl과 `atol 1e-9`로 같고 manifest의 `live.features_fingerprint`도 이번 parquet와 같으면 pkl·manifest를 쓰지 않음) → 군집 후보 fit(`models/clusters.new.pkl`, 유형 CSV·manifest는 `artifacts/parity/`) → `cluster compare --against models/clusters.pkl --types …`(실패하면 `parity_failed=1`, 커밋본 유지) → 유형표 해시가 manifest와 다르면(`types_changed=1`) **명시적 실패**("frozen cluster inputs changed — refreeze by hand" — 자동 fit·publish 없음) → 전체 `check_parity --require-live`(노트북 02~05 포함) | main에서만 bot 커밋 `auto: weekly retrain YYYY-MM-DD`(바뀐 것 없으면 커밋 없음): `models/win_model.pkl`·manifest의 `live` 항목. 실패 또는 compare 실패 시 `parity-failure` 이슈. `model_report.json`·`report-2026.pkl`·`team-2026.pkl`·`clusters.pkl`·`players.json`·`teams.json`·되감기는 고정(덮어쓰지 않음 — 다시 얼리는 것은 사람) |
| `ci.yml` | main 대상 push, PR | `pytest -m "not slow"` + `check_parity --quick` (ubuntu, `timeout-minutes: 30`, 같은 ref의 이전 실행 취소) | 상태 배지 `ci · parity` |

- 권한: `daily`·`weekly`는 `GITHUB_TOKEN`에 `contents: write` + `issues: write`(실패 이슈), `ci`는 `contents: read`. 시크릿 불필요. 커밋 작성자는 `github-actions[bot]`.
- 설치: 일일은 `requirements.txt`(런타임), 주간·ci는 `requirements-dev.txt`(`-r requirements.txt` + 테스트·노트북 패키지). Python 3.12, pip cache.
- 비시즌(경기 없음)에도 `daily.yml`은 매일 돌아간다. `latest.json`은 건드리지 않고 **`data/public/status.json` 한 파일만** (`generated_at`, `run_url`, `commit_sha`, `mode`, `next_game_date`) 갱신해 커밋한다 (내 결정). 한 줄짜리 파일이라 히스토리 오염은 미미하고, 사이트 푸터의 증거 바는 이 파일을 읽으므로 비시즌에도 "오늘 돌아갔다"가 보인다. 사이트는 이때 되감기 모드로 2026 시즌을 보여준다.
- 모든 출력 JSON에 `generated_at`, `commit_sha`, `model_version`, `run_url`(Actions 실행 링크)을 넣는다 → 사이트 푸터의 증거 바.

## 8. 사이트용 데이터 계약

`data/public/` 아래, 사이트는 이것만 읽는다 (`raw.githubusercontent.com/<user>/<repo>/main/data/public/...`).

| 파일 | 내용 |
|---|---|
| `latest.json` | 오늘(또는 가장 최근) 경기 목록: 팀, 구장, 시간, 선발(이름·유형·ERA·K/9·BB/9·상대 성적), 홈 승률, 요인 분해 top 5 (`name, contribution_pp`), `outlook` 블록(아래), 메타(`generated_at`, `commit_sha`, `run_url`, `mode: "live" | "rewind"`, `model_version`). |
| `status.json` | 매일 갱신되는 한 줄 상태: `generated_at`, `run_url`, `commit_sha`, `mode`, `next_game_date`. 푸터 증거 바 전용. (구현 시 추가: `games_today`, `model_version`, `collect_errors`. 4단계: `mode`는 오늘부터 14일 안에 취소되지 않은 경기가 있으면 `live`, 없으면 `rewind`.) |
| `history.csv` | 날짜, gameId, 홈/원정, 예측 홈승률, 결과, 적중 여부. 적중률 추이·최근 예측 표에 사용. |
| `rewind/{season}/{date}.json` | 되감기 모드용 날짜별 `latest.json` 형식. 2026 시즌 전체를 백테스트로 생성. **→ 확정 (4단계)**: 아래 "되감기 파일 모양". |
| `rewind/{season}/index.json` | (4단계 추가) 되감기 목차: `season`, `model_version`, `generated_at`, `commit_sha`, `dates[]`(`date`, `games`, `decided`, `correct`), `accuracy`, `n_decided`, `note`(적중 규칙 한 줄). |
| `players.json` | 선수별: 이름, 팀, 포지션, 시즌, 유형, 소속 확률, 2D 좌표, 주요 스탯, 유사 선수 5명. |
| `teams.json` | 팀별: 실제 승률, 모델 기대 승률, 피타고리안 승률, 로스터 유형 구성 비율, 홈/원정·상대별 승률. |
| `model_report.json` | 적중률·log loss·Brier, 베이스라인 비교, 캘리브레이션 구간표, 피처 중요도, 유형 상성 피처 전후 비교, 클러스터 품질(K별 실루엣, 유형별 인원·대표 선수·특징 스탯). `model_version`과 평가 기간 명시. |

**`outlook` 블록 (오커 카드, 내 결정)** — 시기에 따라 내용이 바뀌고 카드 자리는 같다.
- 포스트시즌: `type: "series"`, 현재 전적, 양 팀 시리즈 우승 확률, 가장 흔한 결말, 최종전까지 갈 확률. 계산: 남은 경기 1만 회 몬테카를로. 오늘 경기는 선발 포함 확률, 이후 경기는 **선발을 뺀 팀 단위 모델**(같은 피처에서 선발 항목만 제거해 따로 학습한 보조 모델)의 확률을 쓴다.
- 정규시즌(되감기 포함): `type: "playoff_race"`, 해당 날짜 기준 양 팀의 가을야구(5위 이내) 진출 확률과 현재 순위. 계산: 잔여 일정을 팀 단위 모델로 1만 회 시뮬. 되감기 생성 시 날짜별로 미리 계산해 `rewind/`에 넣는다.
- 경기 없는 날(라이브 모드에서 비시즌): 카드 제목 "다음 경기까지", `next_game_date`만 표시.

**→ 확정 모양 (4단계, 2026-10-29)**. 시뮬레이션은 `simulate.outlook_for`, 1만 회, `numpy.random.default_rng(42)`. 모든 꼴에 `type`과 `as_of`(기준 날짜)가 있고, 확률·기대 승수는 소수 4자리다.

- `{"type": "series", "as_of", "name", "best_of", "teams": [t0, t1], "head_start": [h0, h1], "wins": [w0, w1], "win_prob": [p0, p1], "most_common_result": "3-2", "goes_distance_prob", "games_remaining_max", "today_game_prob_source", "next_game_date"}` — `config/postseason.yaml`에 등록되고 아직 승부가 나지 않은 시리즈가 있으면 그날 경기가 없어도 이 꼴이다. `wins` = `head_start` + `date < as_of`인 두 팀의 FINAL 경기(경기 전 기준). 오늘 경기는 라이브 승패 모델의 선발 포함 확률(`latest.json` 경기 항목과 같은 반올림 전 값, `run_pipeline` → `outlook_for(today_probs=…)`)로, 이후 경기는 팀 모델로 굴린다 — 오늘 경기의 실제 홈이 다음 순번의 홈과 같을 때만이고, 그러면 `today_game_prob_source: "win_model (starter-inclusive)"`, 아니면(시리즈 도중 경기 없는 날, 오늘 확률이 없을 때) `"team_model"`. 예(2026-10-29, 플레이오프 SS vs HT 1-1, 3차전 SS .5536 선발 포함 · 4차전 .4974 · 5차전 .5629 팀 모델): `win_prob [0.5579, 0.4421]`, `most_common_result "3-2"`, `goes_distance_prob 0.5083` (오늘 경기도 팀 모델이면 0.5279).
- **와일드카드(`head_start`)**: 4위가 1승을 안고 시작하는 2선승제는 `best_of: 3`, `head_start: [1, 0]`(팀0 = 4위), `homes`는 실제 경기 수 `best_of − sum(head_start)` = 2칸. 4위는 1승, 5위는 2승이 더 필요하고, 5위가 1차전을 이기면 1-1로 2차전이 남는다. 2026 와일드카드 LG–두산, 1차전 전 카드 LG 0.8194(경기당 LG 승 확률 p면 1 − (1 − p)²) — 실제로는 LG가 1차전을 이겨 2-0으로 끝났다.
- `{"type": "playoff_race", "as_of", "teams": {code: {"wins", "losses", "rank_now", "exp_wins", "playoff_prob"}}}` — 정규시즌 날짜. `rank_now`는 정수(동률이면 높은 순위), `playoff_prob`의 합은 5(반올림 오차 안).
- `{"type": "next_game", "as_of", "next_game_date"}` — 그 밖(시범경기, 미등록 시리즈, 비시즌). 라이브에서 팀 모델을 읽지 못하면 이 꼴로 대신하고 `collect_errors`에 남긴다.
- **"오늘 경기는 선발 포함 확률" 반영 (최종 수정 라운드)**: 처음 4단계 구현은 오늘 경기도 팀 모델로 값을 매겼다(10-29 3차전 SS 49.7% vs 예측 카드 55.4%, 시리즈 .5279). 이제 위 규칙대로 오늘 경기는 예측 카드와 같은 확률이고, 카드의 `today_game_prob_source`로 구분한다.

**되감기 파일 모양 (4단계 확정)**. `data/public/rewind/2026/{date}.json` — 2026 정규시즌 165일(03-28~10-12) 전부, 날짜당 1개 + `index.json` = 166개, 압축 JSON(`sort_keys`, 들여쓰기 없음) 합계 933,712바이트.

- 최상위: `date`, `mode: "rewind"`, `model_version: "report-2026"`, `team_model_version: "team-2026"`, `starter_source: "actual (boxscore pitching order 1)"`, `generated_at`, `commit_sha`, `run_url`(null), `games[]`, `outlook`(`playoff_race`).
- `games[]`: `latest.json`의 경기 항목과 같은 키(`game_id`, `date`, `time`, `stadium`, `round`, `status`, `status_note`, `home`/`away`(`code`, `name`, `win_pct_season`, `last10`, `run_diff`, `starter`), `home_win_prob`, `starter_known`, `factors`) + `result`. 정규시즌 FINAL과 CANCELED를 (date, game_id) 순으로 넣는다(790행 = FINAL 718 + CANCELED 72). 취소 경기는 `latest.json`과 같은 꼴(`home`/`away`는 `code`만, `home_win_prob: null`, `factors: []`, `result: null`). LIVE로 멈춘 2경기(13352, 13606)는 넣지 않는다.
- `result`: `{"home_score", "away_score", "winner": "HOME" | "AWAY" | "DRAW", "pick": "HOME" | "AWAY", "correct": true | false | null}`. `pick`은 반올림 전 P(홈 승) `>= 0.5`이면 `HOME`(`train_win._correct`와 같은 규칙), `correct = pick == winner`, 무승부는 `null`. 예: 13572(06-12)는 표시 확률 0.5000이지만 반올림 전 값이 0.5 미만이라 `pick: "AWAY"`.
- `index.json`의 `accuracy` 0.594 = 417/702 = `model_report.json`의 2026 시험 정확도(테스트로 고정).

## 9. 웹사이트

- **플랫폼 (사용자 결정)**: Genspark로 제작·호스팅하고, **산출 HTML/CSS/JS를 저장소 `site/`에도 커밋해 GitHub Pages로 같이 띄운다.** 정적 사이트, 데이터는 위 JSON을 `fetch()`. Genspark → 저장소 복사는 사용자가 한다(내보내기 다운로드 → 커밋).
- **사전 확인 (사용자, 1단계 중)**: Genspark가 (a) HTML 파일 내보내기를 지원하는지, (b) 외부 URL `fetch()`가 되는지. (a)가 안 되면 **Genspark는 시안 생성용으로만 쓰고 최종 사이트는 빌더가 `site/`에 직접 만들어 GitHub Pages로 배포**한다. (b)가 안 되면 GitHub Pages 버전이 메인이 된다.
- 빌더는 Genspark에 넘길 입력물을 만든다: 확정 목업 HTML, 8절 데이터 계약, `DESIGN_clay.md`, 샘플 JSON(`data/public/` 실제 파일).
- **디자인 시스템**: `DESIGN_clay.md` 토큰을 그대로. 크림 캔버스 `#fffaf0`, 포화 카드 6색 순환(같은 색 연속 금지), 24px 라운드 피처 카드, 디스플레이 500 웨이트 + 음수 자간, 그림자 없음, 크림 푸터. 폰트: Inter(영문·숫자) + Pretendard(한글). 다크 푸터·회색 캔버스 금지.
- **확정 목업**: `.superpowers/brainstorm/860-1793099185/content/clay-hybrid.html`. 홈 = 핑크/틸 양분 매치업 카드(첫 줄) + 벤토 그리드(크림 요인 → 라벤더 적중률 → 피치 선발 유형 → 오커 시리즈 시뮬 → 틸 유형 지도 → 크림 최근 예측). 선수 탐색 = 크림 유형 지도 + 핑크 선수 카드 + 유사 선수 표.
- **메뉴 4개**: 오늘의 경기(홈) / 팀 / 선수 / 모델 성적표. 우선순위: 홈 + 모델 성적표 → 선수 → 팀.
- **되감기 모드**: 경기가 없는 날은 홈 상단 날짜 칩이 2026 시즌 날짜 슬라이더로 바뀌고, `rewind/`에서 읽는다. "이 날 모델은 이렇게 예측했고 결과는 이랬다"를 보여준다.
- **푸터 증거 바**: "마지막 갱신 {generated_at} KST · Actions 실행 #{run} · 커밋 {sha} · 모델 {version}" — 각각 GitHub 링크.
- 복수 경기가 있는 날(정규시즌 하루 5경기)은 매치업 카드를 세로로 반복하되 첫 경기만 크게, 나머지는 반 높이.

**→ 확정 사항 (5단계, 2026-10-30)**

- **정적 사이트를 먼저, Genspark는 선택적인 다시 입히기**: 사용자 확인 결과 Genspark는 외부 JSON `fetch`와 HTML 내보내기(CSS·JS가 들어간 단일 파일, Cloudflare beacon 스크립트 1개가 붙음)가 모두 된다. 그래도 제작·피드백에 사용자 시간이 들므로 빌더가 완성된 4페이지를 `site/`에 먼저 만들어 GitHub Pages 배포를 설정하고(배포 설정 완료, 첫 push 후 공개 — 공개될 주소 `https://kimminseo2323-prog.github.io/2610_KBO_predict/`), Genspark용 브리프(`docs/site/genspark-brief.md`)와 반영 스크립트(`scripts/import_site.py`)를 둔다. Genspark 제작본은 `check_site.py --strict`를 통과하고 사용자가 더 마음에 들 때만 `site/`를 교체한다.
- **빌드 없는 정적 사이트**: HTML + CSS + 바닐라 ES 모듈. 외부 리소스는 글꼴 CSS(Inter — Google Fonts, Pretendard — jsDelivr `gh/orioncactus/pretendard@`)뿐, 외부 스크립트·트래킹 없음.
- **차트는 인라인 SVG**(`site/assets/charts.js`): 토큰 색·글꼴을 그대로 쓰고 외부 의존을 0으로. 모든 차트에 `role="img"` + `aria-label`과 화면 낭독기용 표.
- **2D 지도 표기는 PCA**: 목업의 "UMAP"은 PCA로 바꿔 적는다(3단계에서 UMAP 제외, 13절).
- **`DATA_BASE` 규칙**: `location.hostname`이 `localhost`/`127.0.0.1`이면 `../data/public`, 아니면 `https://raw.githubusercontent.com/kimminseo2323-prog/2610_KBO_predict/main/data/public`. raw는 `Access-Control-Allow-Origin: *`이라 Pages에서 읽히고, 일일 커밋이 재배포 없이 반영된다(CDN 캐시 최대 5분).
- **캐시 규칙**(최종 리뷰에서 바꿈 — 처음에는 모든 요청에 `?v=`): 매일(하루 두 번) 바뀌는 `status.json`·`latest.json`·`history.csv`·`rewind/2026/index.json`만 `?v=<Date.now()>` + `cache: "no-store"`로 읽고(`fetchJSON(name, { fresh: true })`), 되감기 날짜 파일·`players.json`·`teams.json`·`model_report.json`은 많아야 주 1회 바뀌므로 브라우저 기본 캐시를 쓴다(되감기 슬라이더를 오갈 때 같은 날짜 파일을 다시 받지 않게).
- **되감기 규칙**: `status.json.mode === "rewind"`이면 홈이 `rewind/2026/index.json`의 마지막 날짜로 열리고 날짜 슬라이더를 보인다. `live`면 `latest.json`을 보이되 "2026 시즌 되감기" 토글을 둔다. `?date=YYYY-MM-DD`는 그 날짜 되감기로 바로 연다.
- **확정 목업 위치**: `docs/design/clay-hybrid.html`(`.superpowers/` 원본을 복사, `.superpowers/`는 gitignore).
- **배포**: `.github/workflows/pages.yml`(main의 `site/**` push + 수동 실행, `configure-pages` → `upload-pages-artifact` `path: site` → `deploy-pages`, `concurrency: pages`·`cancel-in-progress: false`). `GITHUB_TOKEN`으로는 Pages 사이트를 만들 수 없어(`enablement: true`도 실패) 저장소 설정에서 Pages(Source = GitHub Actions)를 push 전에 켠다. `site/`는 일일 커밋 대상이 아니다.
- **계획과 다르게 받아들인 것 — 팀 페이지 가을야구 되감기 표본**: 계획은 날짜 5개(개막·5/1·7/1·9/1·마지막)였지만, 선이 너무 성겨 시즌 흐름이 안 보여 `rewind/2026/index.json`의 165일 중 매 7번째 날 + 마지막 날(25개 날짜 파일, 한꺼번에 받음)로 그린다(`teams.js` `REWIND_STRIDE`). 날짜 파일은 기본 캐시라 두 번째 방문부터는 다시 받지 않는다.

## 10. 저장소

- GitHub public 저장소: `https://github.com/kimminseo2323-prog/2610_KBO_predict` (2026-10-27 생성).
- README: 아키텍처 다이어그램(Actions → JSON → 사이트), 사이트 링크, Actions·parity 배지, 모델 성적 요약표, 노트북 목차, 데이터 출처·비공식 API 고지, 실행 방법.
- 라이선스 MIT(코드). 데이터 폴더는 "출처: MyKBOStats(비공식 팬 사이트, robots.txt Crawl-delay 준수), 개인 학습용" 고지.
- `.gitignore`에 `.superpowers/`, `artifacts/`, 가상환경.
- 현재 작업 폴더(`261027_KBO`)는 아직 git 저장소가 아님 → 빌더가 `git init` 후 첫 커밋에 이 설계 문서를 포함.

## 11. 도구 분담 (제안, 사용자 조정 가능)

- **Claude Code**: 계획 → 수집 파이프라인 → 피처 → 모델 → Actions → 노트북 초안.
- **Codex**: 독립 코드 리뷰(누수 검사 집중), parity 스크립트 교차 검증, 노트북 설명 다듬기.
- **Genspark**: 목업 HTML과 데이터 계약(8절)을 입력으로 사이트 제작·배포.

## 12. 단계

**사용자 결정: 한국시리즈가 끝나기 전에 라이브 기록을 남기기 위해 얇은 수직 슬라이스를 먼저 공개한다.** 초기 커밋이 거칠어도 "개선 과정"으로 보여준다. 단, 누수 반목표는 v0.1부터 지킨다 (경기 전 데이터만 사용).

0. **수직 슬라이스 v0.1 — 완료 (2026-10-28)**: `git init` + public 저장소 → MyKBOStats 수집기(2026 시즌 전체) → 최소 피처(팀 승률, 최근 10경기, 득실차, 홈/원정; 선발 피처는 소스 부재로 제외)로 로지스틱 회귀 → `daily.yml`(KST 09:07/17:07) → `latest.json`, `history.csv`, `status.json` bot 커밋. README v0.1. 노트북은 아직 없음. 지표: 테스트 구간 적중률 .603 (베이스라인 .536/.594).
1. **데이터 — 완료 (2026-10-29)**: 2015~2025 백필(+2026 월별 저장으로 이전)을 로컬에서 실행해 시즌별 정규시즌 720경기(2022·2023은 719경기 + 멈춘 LIVE 1건, 2026은 718경기 + 2건)를 확보하고, 시즌 경계는 `REGULAR_SEASON`과 `EXCLUDED_GAMES`(2024 5위 결정전)로 고정했다. 수집기는 경기 단위 실패 허용·멈춘 LIVE 보정·실패 이슈 자동 생성으로 보강했고, 노트북 01(`notebooks/01_데이터_수집과_살펴보기.ipynb`)을 실행 결과와 함께 커밋했다.
2. **피처 + 승패 모델 — 완료 (2026-10-29)**: 예고 선발 파서·수집기(`data/raw/{season}/starters.jsonl`)를 붙이고, 누수 없는 피처 26개(팀 19 + 선발 7, `features.py`)로 2015~2026 정규시즌 8,465경기 데이터셋(`data/processed/features.parquet`, gitignore, SHA256은 `models/manifest.json`)을 만들었다. LR과 LightGBM을 같은 인터페이스로 감싸 Platt/isotonic 캘리브레이션과 요인 분해(LR 계수, LightGBM 내장 TreeSHAP `pred_contrib`)를 붙였고, 2015~2024 학습 / 2025 검증(LightGBM best_iteration 52, 캘리브레이션·알고리즘 선택) / 2026 홀드아웃 평가(학습·선택에 미사용)로 `report-2026`(`models/report-2026.pkl`, `data/public/model_report.json`)을, 같은 알고리즘·방법을 2015~2026 전체로 다시 학습해 라이브 v0.2(`models/win_model.pkl`)를 만들었다. 일일 파이프라인은 예고 선발로 추론하고 `latest.json`에 선발 블록과 요인 상위 5개를 넣는다. 노트북 02·03을 실행 결과와 함께 커밋했고(각각 parquet SHA256, `model_report.json` 일치 확인), 테스트 179개. 결과(2026, 702경기): 선택 모델은 LR + Platt, 정확도 .594 / log loss .671 / Brier .239 (LightGBM .591 / .673 / .240). 베이스라인은 홈팀 승 .514, 승률 높은 팀 .554, 선발 ERA 낮은 팀 .567. 2025에서 미리 정한 비교 대상(선발 ERA) 대비 +2.7%p, McNemar p = .215로 **2절 목표("+3%p, 통계적으로 유의")에는 아직 못 미친다**(홈팀 승 대비 p < .001, 승률 대비 p = .079). 이 지표는 실제 선발을 경기 전에 안다는 가정 위의 값이며, 선발 피처를 뺀 팀 피처 19개 모델은 .547 / .687로 승률·선발 ERA 규칙보다 약하다(홈팀 승 .514보다는 높음). 2026 시즌은 어떤 학습·선택에도 쓰지 않았다. 다만 개발 중에 2026 지표를 확인했고, 캘리브레이션 선택 절차를 한 번 바꿨다(R7: 검증 시즌에서 적합·선택을 함께 하던 방식이 isotonic을 편애하는 표본 내 편향). 이전 절차의 결과는 LightGBM + isotonic, 정확도 .588 / log loss .679(p = .321)였다(커밋 24aff45의 `model_report.json`).
3. **클러스터링 — 완료 (2026-10-29)**: 경기 페이지 하단 기록표 파서로 로컬 캐시 9,362경기를 재파싱해 박스스코어에 2루타·3루타·도루와 한글 이름을 보탰고(기존 칸 불변, `features.parquet` SHA256 동일; 지표 라벨 미매칭 127건, 별칭 31명), `player_stats.py`가 정규시즌 FINAL을 선수·시즌으로 합산한다. `cluster.py`가 비율 지표(타자 6, 투수 5) → 표준화 → K-means(K=4~7, `실루엣 + 유지율`로 선택) → 소속 확률 → PCA 2D → 코사인 유사 선수 5명을 만들고, 중심은 2015~2025로만 맞춰 2026은 배정만 한다(`models/clusters.pkl`, `clusters-2026`, `types_sha256`은 `models/manifest.json`). 결과: 타자 K=4(실루엣 .1715, 유지율 .6536; 파워형 299·장타 지향형 368·컨택형 456·주루형 204), 투수 K=4(.2045, .5322; 선발형 512·스윙맨형 301·제구 불안 불펜형 368·삼진 불펜형 410), 이름은 사람이 붙여 `config/cluster_labels.yaml`. GMM 일치율(타자 tied .843, 투수 tied .750)이 0.95 미만이라 소속 확률은 두 그룹 모두 중심 거리 소프트맥스(`kmeans_softmax`)다. `cluster publish`가 `players.json`(선수-시즌 2,918개, 압축 1.77 MB)과 `teams.json`(팀-시즌 120개, `model_expected`는 2026만)을 만들고, 일일 파이프라인은 선발 블록에 직전 시즌 투수 유형(`type`)을 넣는다. 직전 시즌 유형으로 만든 상성 피처 9개(`bat_type{t}_diff`, `starter_type{t}_diff`, `types_known`)를 같은 알고리즘·분할로 넣어 본 결과 검증(2025) log loss .67711 → .67783, 시험(2026) 정확도 .594 → .591 / log loss .67123 → .67135, McNemar p = .845로 채택 기준(검증 log loss 0.001 개선)에 못 미쳐 `adopt: false`, 라이브 v0.2는 그대로다(`types_known` 커버리지 26.9%, 2026은 15.5%). 2025 검증 비교는 중심이 2025를 본 전이적 비교이고 2026 시험만 엄밀한 시간 외 비교다(`validation_scope`). `model_report.json`의 `matchup_feature_ablation`·`cluster_quality`를 채웠고(기존 키의 값은 불변), 노트북 04(`notebooks/04_선수_유형_클러스터링.ipynb`, `types_sha256`·`matchup_sha256` 일치 확인)를 실행 결과와 함께 커밋했다. 노트북 03에 상성 전후 비교 절을 더했다. 테스트 261개.
4. **자동화 완성 + parity — 완료 (2026-10-29)**: 의존성을 `requirements.txt`(런타임)와 `requirements-dev.txt`로 나누고 노트북 실행 테스트에 `slow` 마커를 달아 `ci.yml`(main push·PR: `pytest -m "not slow"` + `check_parity --quick`)을 붙였다. 선발 없는 팀 모델을 `models/team-2026.pkl`(`train_win team`, 팀 피처 19개, `ablation.no_starter`와 같은 모델 — 2026 정확도 .547)로 저장하고, `simulate.py`가 그 확률로 가을야구(5위 이내) 진출 확률과 포스트시즌 시리즈 확률을 몬테카를로 1만 회로 계산한다(`config/postseason.yaml`, seed 42). `scripts/build_rewind.py`가 report-2026으로 2026 정규시즌 165일을 날짜별로 다시 예측해 `data/public/rewind/2026/`(166개 파일, 933,712바이트, 실제 선발, 경기별 `result`, `playoff_race` 전망)을 만들었고, 적중 417/702 = .594가 `model_report.json`과 같다. `run_pipeline`은 `latest.json`에 `outlook`(series / playoff_race / next_game)을 넣고, 시범경기 `round: "preseason"`, 비시즌 `mode: "rewind"`, 공개 파일·`games.jsonl`·`starters.jsonl` 원자적 쓰기, 경기 없는 날 선발 요청 생략, 박스스코어 없는 FINAL 재수집을 더했다. 예(2026-10-29): 플레이오프 SS vs HT 1-1 → SS .5579(오늘 3차전은 선발 포함 .5536, 4·5차전은 팀 모델), 가장 흔한 결말 3-2, 5차전 확률 .5083. `scripts/check_parity.py`가 피처·상성 parquet 값 지문, 유형표 해시와 군집 재적합, 보고서(상대 오차 1e-9), 세 모델의 예측, 사이트 JSON, 되감기 166개 파일을 다시 만들어 비교하고 노트북 02~05를 실행한다(Windows `--quick` 38.6초, 전체 약 90초). Linux ci에서 parquet 파일 바이트가 Windows와 달라 한 번 실패(실행 40879259726)한 뒤 판정을 값 지문(`features_fingerprint` `752b4319…`, `matchup_fingerprint` `3419c8c1…`)으로 바꿔 통과했다(40882643905). `weekly_retrain.yml`(월요일 03:07 KST)이 라이브 재학습(`--skip-if-same`, 예측 + manifest 지문)·군집 재계산 비교(`cluster compare --types`, 유형표가 바뀌면 실패 — 사람이 다시 얼린다)·전체 `check_parity --require-live`(노트북 02~05 포함)를 돌리고 실패하면 `parity-failure` 이슈를 연다. 노트북 05(`notebooks/05_오늘_경기_예측.ipynb`, 41셀, 약 5초)가 2026-10-29 경기 하나를 상태 → 예측·요인 → 시리즈 시뮬레이션 → 되감기 → parity 순으로 따라간다. `model_report.json`의 기존 값과 `report-2026.pkl`의 예측, `clusters.pkl`은 바뀌지 않았다 — 값 지문 키를 넣으려고 보고서를 한 번 다시 만들어(`ace0de5`) `model_report.json`에 `features_fingerprint`가 더해지고 `report-2026.pkl`은 `trained_at` 때문에 바이트만 바뀌었다. 최종 수정 라운드에서 시리즈의 오늘 경기 = 선발 포함 확률(8절), 와일드카드 `head_start`, 노트북 03·04의 플랫폼 간 판정(`kbo_predict.parity`), 정규시즌 기록표만으로 한글 이름 투표, 얼린 시즌 박스스코어 재수집 금지를 더했다. 테스트 337개 + slow 6개. 남은 한계(2027 라이브 팀 모델, 2027 `REGULAR_SEASON` 등록 등)는 이월 문서 "5단계 전에".
5. **사이트 — 완료 (2026-10-30)**: `data/public/`만 읽는 정적 사이트 4페이지(오늘의 경기 `index.html` / 팀 `teams.html` / 선수 `players.html` / 모델 성적표 `report.html`)를 `site/`에 만들고 GitHub Pages 배포를 설정했다(`pages.yml`; 배포 설정 완료, 첫 push 후 공개 — 공개될 주소 `https://kimminseo2323-prog.github.io/2610_KBO_predict/`). 공통 레이어는 `site/assets/`의 `tokens.css`(`DESIGN_clay.md` 토큰), `app.css`, `app.js`(데이터 계층 `DATA_BASE`·`fetchJSON`·`fetchCSV`, `TEAMS`·`FACTOR_LABELS`·`TYPE_COLORS`, 내비·증거 바·오류 상자), `charts.js`(인라인 SVG 차트 5종)이고, 페이지마다 CSS·JS 한 쌍이다. 홈은 핑크/틸 매치업 카드 + 벤토 6장(요인·적중률·선발 유형·전망·유형 지도·최근 예측), 비시즌에는 2026 되감기 슬라이더(165일). 팀은 순위표(결정전·상대 전적 동률 규칙)·로스터 유형 구성·상대 전적 격자·가을야구 확률 되감기, 선수는 유형 지도·선수 카드·비슷한 선수·유형 모델, 성적표는 모델·기간 배지·2026 홀드아웃·신뢰도 곡선·중요도·변형 비교·유형 품질·라이브 기록. 페이지 요소별 데이터 키는 `docs/site/data-contract.md` 매핑 표로 고정했고, `scripts/check_site.py --strict`가 페이지 구조(doctype·lang·title·viewport), 메뉴 4개 순서와 `aria-current`, "GitHub에서 보기", 증거 바 `#evidence`, 외부 리소스 허용 목록(연결한 로컬 스타일시트의 `@import`·`url()`, JS 문자열 속 `https://` 주소 포함)·트래킹 금지·`assets/` 상대 경로, `TEAMS`·`FACTOR_LABELS`·`TYPE_COLORS`의 파이썬 원본 일치, 매핑 표 키 경로의 실재, 홈 `?fixture=edge` 지원을 검사한다(29항목 OK). Genspark 브리프(`docs/site/genspark-brief.md`: 공통 규칙·페이지별 프롬프트 4개·수락 체크리스트·내보내기 절차)와 반영 스크립트(`scripts/import_site.py`: 백업 → beacon 등 허용 밖 `<script>`·`<link>` 제거 → `file://`·루트 경로 상대화 → `check_site --strict`, 실패 시 복원)를 두었다. 사이트 테스트 32개(`tests/test_site.py`, 페이지·검증 도구 29 + 반영 스크립트 3), 전체 `-m "not slow"` 369개(최종 리뷰 수정 뒤). 홈·성적표·선수·팀 각 태스크는 컨트롤러의 1280px·360px 스크린샷 리뷰를 거쳤다.
6. **마무리**: README, 배지, 한 달 무인 운영 확인.

## 13. 빌더에게 맡기는 것

- 정확한 피처 목록과 하이퍼파라미터, 캘리브레이션 방식 선택.
- 클러스터 K와 유형 이름(프로파일 보고 결정), PA/IP 임계값 미세 조정.
- MyKBOStats 페이지의 결측·이상치 처리 규칙 (단, 처리 규칙은 노트북 01에 설명으로 남길 것). 사이트에 LIVE로 멈춘 경기(2026년 2건)의 보정 방식.
- 사이트의 차트 라이브러리 선택 (단, 디자인 토큰을 따를 것).
- Actions의 정확한 cron 분(分) 단위 시각, 재시도 정책. (구현 시 확정: 모든 cron은 매시 07분 — 일일 09:07·17:07, 주간 월 03:07 KST → 7절)
- 테스트 범위 (최소: 피처 함수의 누수 테스트 — "경기 당일 이후 데이터가 피처에 들어가면 실패").

구현하며 확정한 수집 보정 규칙(1단계):

- **LIVE로 멈춘 경기**: 사이트가 종료로 바꾸지 않고 LIVE로 남긴 경기는, 날짜가 오늘−2일 이전일 때 경기 페이지를 다시 확인한다. 페이지가 FINAL이고 양 팀 점수가 모두 있을 때만 FINAL로 보정하고, 아니면 LIVE로 그대로 두며 학습에서 제외한다. 점수를 추측해 채우지 않는다 (2026년 13352, 13606은 LIVE 유지).
- **"Delayed" 페이지**: 경기 페이지가 "Delayed"(지연)라고 말하면 종료로 보지 않고 LIVE로 분류한다. 파싱에 실패하거나 FINAL이 아닌 페이지는 HTML 캐시에서 지운다.

구현하며 확정한 규칙(2단계):

- **팀 OPS 대체**: 박스스코어에 2루타·3루타가 없어 OPS·장타율을 만들 수 없다. 대신 근사 출루율(OBP, 희생플라이 없음) + 타석당 홈런 비율 + 삼진 비율(K%) + 볼넷 비율(BB%)을 쓴다.
- **구장·요일 피처 제외**: 구장은 홈팀과 거의 1:1이라 홈 승률(`home_venue_pct`)과 겹치고, LR에 범주형을 넣는 비용이 크다. 요일도 같은 이유로 뺐다.
- **선발의 상대팀 상대 성적 제외**: 시즌 초에는 대부분 결측이다.
- **선발 지표의 창**: 선발 ERA·FIP·K/9·BB/9·누적 이닝은 당해 + 직전 시즌 합산(시즌 초 표본 부족 완화), 최근 3선발 실점도 같은 창에서 센다(라이브·학습 피처 일치).
- **`starter_known`**: 양쪽 선발이 모두 확인되고 기록이 있을 때만 1. 한쪽이라도 없으면(예고 미발표 등) 0이고 선발 차이 피처 6개는 모두 결측(NaN)이다.
- **실제 선발 / 예고 선발 불일치**: 학습·검증·시험 행의 선발은 박스스코어의 실제 선발(투수 순서 1)이다. 과거 예고 선발 기록이 없기 때문이다. 그래서 보고서 지표는 "경기 전에 선발을 정확히 안다"는 가정 위의 값이고, `model_report.json`의 `starter_source`에 이를 적는다. 하한선으로 선발 피처를 뺀 팀 19개 모델(`ablation.no_starter`)을 같은 절차로 학습해 함께 보고한다. 라이브는 예고 선발을 쓰며, 예고와 실제가 다른 경기의 오차는 `history.csv`의 라이브 기록에 드러난다.
- **캘리브레이션 선택 절차**: 보정기는 학습 시즌들의 leave-one-season-out(LOSO) OOF 예측으로 맞추고, 2025 검증은 none/Platt/isotonic의 log loss 점수만 매겨 방법을 고른다. 검증 세트에서 보정기를 맞추고 같은 세트로 고르면(in-sample 선택) 유연한 isotonic이 유리하게 편향되기 때문이다. 결과는 두 알고리즘 모두 Platt. 이 절차는 개발 중 한 번 바뀌었다(R7). 2026은 어떤 학습·선택에도 쓰지 않았지만, 바꾸기 전에 2026 지표를 이미 확인했다. 이전 절차(2025에서 적합·선택)의 결과는 LightGBM + isotonic, 2026 정확도 .588 / log loss .679 / Brier .242, 선발 ERA 기준선 대비 McNemar p = .321(커밋 24aff45). 그래서 2026 지표를 "한 번도 보지 않은 1회 평가"라고 부르지 않는다.
- **라이브 캘리브레이터**: 라이브 모델은 2015~2026 전체로 학습해 "안 본 데이터"가 없으므로, 보정기를 전체 시즌의 LOSO OOF 예측으로 맞춘다.
- **유의성 비교 대상 사전 지정**: McNemar 검정의 비교 대상 기준선은 2025 검증에서 가장 강한 규칙(선발 ERA 낮은 팀)으로 기계적으로 정한다(이 규칙 자체는 Codex 교차 검토 이후, 즉 2026 지표를 한 차례 본 뒤에 도입했다). 나머지 기준선과의 p값은 참고로만 함께 적는다.
- **요인 pp는 1차 근사**: 보정 전 로그 오즈는 피처별 기여 + 기본값으로 정확히 나뉘지만(`contrib.sum + base == logit(p_raw)`, 테스트로 검증), 퍼센트포인트 변환은 `기여 × Platt 기울기 × p(1−p) × 100`의 1차 근사라 합이 확률 차이와 정확히 같지 않다. `latest.json`에는 기본값을 포함해 절댓값 상위 5개를 넣는다.
- **보고서 고정과 라이브 재학습 분리**: `train_win report`는 `model_report.json`이 이미 있으면 `--force` 없이 거부한다. `train_win live`는 보고서에서 selected·보정 방법·LightGBM 트리 수만 읽고 parquet 해시 일치는 요구하지 않는다(경기가 쌓이면 다시 학습). 대신 `models/manifest.json`이 모델별로 (파일 SHA256, 버전, 그 모델을 만든 parquet SHA256)을 남기고, 각 명령은 자기 항목만 갱신한다.
- **예고 선발 덮어쓰기 방지**: 예고 선발 파서는 페이지의 `og:url` 경기 번호를 확인해 다른 경기·챌린지 페이지를 오류로 처리하고, 저장은 알려진 선발을 미정(None)으로 되돌리지 않는다.
- **SHAP 구현**: `shap` 패키지 대신 LightGBM 내장 TreeSHAP(`pred_contrib=True`)을 쓴다. 의존성을 늘리지 않고 같은 값을 얻는다.
- **모델 두 벌의 파일명**: 평가용은 `models/report-2026.pkl`(`model_version: "report-2026"`), 라이브는 `models/win_model.pkl`(`v0.2`). `models/manifest.json`이 피처 parquet와 두 pkl의 SHA256을 기록한다.
- **Codex 교차 검토**: `codex exec`(0.155.0, `--sandbox read-only`)로 `features.py`·`train_win.py`·`predict.py`를 누수·재현성·통계 관점에서 검토했고, 3건을 반영했다(선발 가정 명시와 선발 없는 변형, 유의성 비교 대상 val 사전 지정, 요인 pp에 Platt 기울기 반영).

구현하며 확정한 규칙(3단계):

- **2루타·3루타·도루 소스**: 4.2의 두 후보 중 경기 페이지 하단 기록표(`data-game-section="records"`)를 쓴다. 선수 페이지는 선수당 1요청 × 수천 명이라 5초 간격으로 며칠이 걸린다. 기록표는 조사한 150경기(2015~2026) 전부에 있고 형식은 `이름 (1st inning)`, `이름 (1st, 9th inning)`(이닝 수 = 개수)로 일정하다. 희생플라이·희생번트는 없으므로 PA = AB + BB + HBP 그대로.
- **선수 한글 이름**: 같은 기록표의 `title` 속성(`2루타: 신종길(1회) 필(1회)`)을 영문 항목과 순서로 맞춰 모은다(한국 선수는 이름 전체, 외국인은 통용 표기 "필", "니퍼트"). 경기별 투표에서 최빈 이름이 득표의 60% 이상이면 채택한다.
- **기록표 이름 매칭**: exact → 단어 접미어("Andy Van Hekken" ↔ 행 "Van Hekken") → 다른 경기에서 투표로 얻은 한글 이름 힌트(`ko_names`). 후보가 0명이거나 2명 이상이면 미매칭으로 남긴다(예외 없음). 개명 선수는 재파싱 스크립트가 "미매칭 이름이 5경기 이상 등장하고 그 경기 로스터 교집합에 선수 1명만 남으며, 그 한글 이름이 다른 선수의 다수결 이름이 아닐 때"만 별칭으로 연결해 `data/raw/name_aliases.json`에 기록한다(31명, 예: 한동민→한유섬). 결과: 지표에 쓰이는 라벨(2B/3B/SB/HR) 미매칭 127건(테스트 상한 200), 실책·피홈런 투수 포함 총 457건(상한 500). 캐시 없는 경기 18개는 새 칸이 None이다.
- **군집 피처**: 타자 `k_pct, bb_pct, hr_pct, iso, babip, sb_rate`, 투수 `k_pct, bb_pct, hr_pct, babip, start_share`(타자당 비율). GB/FB는 추정할 수 없고 HR/FB 근사도 FB가 없어 뺐다. `start_share`(선발/등판)는 역할 비율이라 "비율 지표만" 원칙 안에 둔다.
- **자격**: 타자 PA ≥ 200, 투수 IP ≥ 50(아웃 150) 또는 구원 등판 ≥ 30. 5.2의 값 그대로(분포는 노트북 04). 선수 시즌 집계는 승패 모델과 같은 `regular_finals` 필터(정규시즌 FINAL, 박스스코어 있는 경기)라 포스트시즌은 빠진다.
- **K 선택**: K=4~7 각각 실루엣(맞춤 행)과 연도 간 유형 유지율(연속 두 시즌 모두 자격인 선수 중 같은 유형 비율)을 재고, `score = 실루엣 + 유지율`이 최대인 K(동률이면 작은 K). 타자·투수 따로.
- **유형 번호와 이름**: K-means 라벨을 중심 프로파일로 다시 번호 매긴다(타자는 표준화 `hr_pct` 중심 내림차순, 투수는 `start_share` 내림차순 → 동률 시 `k_pct` 내림차순). 이름은 그 프로파일을 보고 사람이 붙여 `config/cluster_labels.yaml`에 둔다.
- **2D 시각화는 PCA**: UMAP은 `umap-learn` + `numba` 의존성이 커서 제외했다.
- **GMM은 소속 확률 전용**: 라벨은 K-means로 고정하고, GMM은 소속 확률 후보로만 쓰며 두 방법의 일치율을 `cluster_quality`에 적는다. 5.2의 "더 설명 잘 되는 쪽 채택"을 이렇게 결정론적으로 푼다(실제 방식은 다음 규칙).
- **소속 확률**: GMM(tied/diag/full, K-means 중심으로 초기화)을 맞춰 K-means 유형과의 일치율을 재고, 0.95 미만이면(타자 tied .843, 투수 tied .750) 중심 거리 소프트맥스 `exp(-d²/(2·s²/D))`(s² = 맞춤 행의 군집 내 평균 제곱거리, D = 피처 수)를 쓴다. 표시 유형과 최대 확률이 항상 일치하도록 한 결정이며, 보정된 확률이 아니라 상대적 확신도다. GMM 일치율은 `cluster_quality.gmm_candidates`에 남긴다.
- **유사 선수**: 같은 표준화 공간의 코사인 유사도 상위 5개 선수-시즌. 같은 그룹 안에서 고르고, 같은 선수의 다른 시즌은 후보에서 뺀다(한 시즌만 자격인 선수도 5명을 받는다).
- **중심 적합 범위**: 2015~2025로 맞추고 2026은 배정만 한다. 학습 시즌(2015~2024) 경기의 직전 시즌 유형은 2025까지 본 중심에서 나오므로 미래 시즌 통계가 경계에 영향을 주지만, 결과(승패)는 보지 않는 비지도 적합이다. 2026 시험 구간은 2026 통계를 전혀 보지 않은 중심이다.
- **상성 피처 모양**: 홈 − 원정 차이 꼴. `bat_type{t}_diff`(타선의 유형 t PA 비중 차이, K_b개), `starter_type{t}_diff`(선발 유형 one-hot의 차이, K_p개), `types_known`(양 팀 타선 PA의 유형 파악 비중이 모두 0.5 이상이고 양 선발 유형이 모두 있으면 1). 타선 구성은 그 시즌 그 팀에서 지금까지 기록된 PA를 직전 시즌 유형으로 가중한다(라인업은 경기 전에 모르므로). 선발은 다른 선발 피처처럼 백테스트는 실제 선발, 라이브는 예고 선발. 별도 parquet `data/processed/matchup.parquet`에 저장해 `features.parquet`와 보고서의 기존 숫자를 건드리지 않는다.
- **전후 비교 규약**: 선택된 알고리즘·캘리브레이션·트리 수 그대로, 피처만 26개 → 26 + 상성 9개로 늘려 같은 분할로 학습·평가한다. 2025 검증 log loss가 0.001 이상 좋아지면 `adopt: true`. 채택되더라도 라이브 모델 교체·일일 추론 배선은 4단계(주간 재학습과 함께)로 미룬다.
- **상성 비교의 검증 범위**: 2025 검증 비교는 중심이 2025 성적을 본 전이적(transductive) 비교, 2026 시험만 엄밀한 시간 외 비교다(`validation_scope`). 채택 기준(검증 log loss 0.001 개선)에 미달해 `adopt: false`이고, 라이브 모델 v0.2는 바뀌지 않는다.
- **재현성과 라벨 경로**: `config/cluster_labels.yaml` 기본 경로는 패키지 위치 기준이다(작업 폴더와 무관). 계산을 단일 스레드(`threadpool_limits(1)`)로 묶어 비트 단위로 재현한다. Linux BLAS에서는 마지막 비트가 다를 수 있어 커밋된 pkl이 기준이다(4단계 parity 항목).
- **사이트 데이터 형식**: `players.json`은 압축 JSON(들여쓰기 없음), 유사 선수 항목은 `player_id/season/similarity`만 담고 이름은 같은 파일에서 조회한다. 1.77 MB(gzip -9 기준 약 270 KB). `teams.json`의 `model_expected`는 2026만(report-2026 홀드아웃 예측 평균)이고 2015~2025는 학습·검증 시즌이라 null이다.
- **라이브 선발 유형**: 일일 파이프라인은 `models/clusters.pkl`이 있으면 선발 블록에 직전 시즌 투수 유형(`type: {id, name}`)을 넣고, 직전 시즌 자격이 없으면 null이다(예: Shirakawa는 2024·2026만 자격).
- **Codex 교차 검토**: `codex exec`(`--sandbox read-only`)로 상성 피처 누수(직전 시즌만·중심 적합 범위), 군집 재현성, 전후 비교 규약, 기록표 매칭 규칙을 검토했고, 3건을 반영했다(검증 비교를 전이적으로 명시한 `validation_scope`, 소프트맥스에서는 자명하게 1이 되는 일치율 대신 `argmax_consistent`·`membership_note`, 캐시 없는 경기에서 재파싱 2차 패스가 중단되던 문제). 유사 선수의 코사인 유사도는 5.2대로 유지했다.

구현하며 확정한 규칙(4단계):

- **팀 모델 파일**: `models/team-2026.pkl`(`model_version: "team-2026"`, 19개 `TEAM_FEATURES`, 2015~2024 학습·2025로 트리 수·캘리브레이션 선택은 report와 같은 방법, train LOSO OOF 보정기). 2단계의 `ablation.no_starter`와 같은 절차이므로 그 번들을 저장하는 `train_win team` 명령으로 만든다(보고서 숫자 불변, 2026 정확도 .547 / log loss .687 / Brier .247 = `ablation.no_starter.test`). 되감기와 라이브 `outlook`이 둘 다 이 파일을 쓴다. 2015~2026으로 학습한 라이브 팀 모델은 2027 시즌 전으로 이월.
- **시뮬레이션의 경기 확률**: 잔여 경기마다 "기준 날짜 시점의 팀 상태"로 팀 모델 확률을 한 번 계산하고(`date=on` 고정 — 가을야구와 시리즈 경로 둘 다), 시뮬레이션 중에는 상태를 갱신하지 않는다(한 경기 결과가 다음 경기 피처를 바꾸는 효과 무시, 불펜 피로 피처도 고정). 스펙 "1만 회" 그대로, `numpy.random.default_rng(42)`.
- **가을야구 정의와 동률**: 정규시즌 5위 이내, 승률(무승부 제외)만 본다(상대 전적·순위 결정전 없음). 계획 시점에는 "동률이면 평균 순위"였으나, 그러면 경계 팀의 몫이 체계적으로 줄어 개막일 확률 합이 4.83이 되었다. 그래서 동률 그룹이 걸친 순위 [lo, hi]에 대해 각 팀에 `clip((5−lo+1)/(hi−lo+1), 0, 1)`을 주는 분수 배점으로 바꿨다 → 시뮬레이션마다 정확히 5자리. `rank_now`는 정수 min-rank(동률이면 높은 순위). 남은 경기가 0이면 현재 순위로 확정(0/1, 동률은 같은 분수 배점).
- **잔여 정규시즌 경기**: 기준 날짜 이후 경기와, 기준 날짜 전인데 FINAL이 아닌 경기(LIVE로 멈춘 2경기)를 남은 경기로 본다 — 그래야 모든 팀이 144경기로 맞는다. 취소 경기는 별도 재편성 행이 있으므로 뺀다.
- **시리즈 입력**: 현재 시리즈(팀 2개, `best_of`, 1차전 날짜, 경기별 홈팀, 선택 `head_start`)는 `config/postseason.yaml`의 시즌별 목록에서 읽는다(사람이 유지). 미정 팀·날짜가 null이면 그 시리즈는 건너뛰고, `homes`가 없으면 모든 경기를 팀0 홈으로 본다. `head_start: [h0, h1]`(기본 `[0, 0]`)은 전적에 처음부터 더하는 승수이고 경기가 아니므로 `homes`는 `best_of − sum(head_start)`칸이다 — 와일드카드 = `best_of: 3, head_start: [1, 0], homes: [4위, 4위]`(처음 구현의 `best_of: 1` 단판은 5위가 1차전을 이기면 바로 끝나 틀렸다). 오늘 경기가 그 시즌 목록의 어느 시리즈에도 없으면(예: 시범경기) `next_game` 꼴.
- **시리즈 전적은 경기 전 기준**: 두 팀의 FINAL 경기를 `date < on`으로만 센다(당일 FINAL 제외, 가을야구·되감기와 같은 의미). 활성(아직 승부가 나지 않은) 등록 시리즈가 있으면 경기 없는 날에도 `series` 카드를 내고 `next_game_date`를 붙인다(시리즈 도중 "다음 경기까지"가 나오지 않게). 포스트시즌 무승부는 홈 슬롯 오프셋에 반영한다(무승부도 한 경기 순번을 쓴다). 무승부로 `homes`가 모자라면 마지막 경기의 홈을 반복한다. 취소 경기는 같은 순번으로 다시 치른다고 본다.
- **시리즈의 오늘 경기 확률**: `run_pipeline`이 오늘 취소 아닌 경기마다 `predict.raw_prob`(예측 항목과 같은 반올림 전 값 — `predict_game`과 되감기 적중 판정도 이 함수 하나를 쓴다)를 `outlook_for(today_probs={game_id: p})`로 넘긴다. `simulate.series_probs`는 첫 남은 경기가 오늘 두 팀 경기이고 그 홈이 다음 순번의 홈과 같을 때만 그 칸을 이 확률(팀0 기준으로 뒤집음)로 바꾼다. 카드의 `today_game_prob_source`가 출처다.
- **`round` 표기**: 정규시즌 개막 전 경기(2026-03-20~24 시범경기)는 `preseason`, 정규시즌 종료 후는 `postseason`(기존 코드는 둘 다 `postseason`). `EXCLUDED_GAMES`(2024 5위 결정전)는 `postseason`.
- **status.json `mode`**: 오늘부터 14일 안에(양끝 포함) 취소되지 않은 그 시즌 경기가 있으면 `live`, 없으면 `rewind`(비시즌). `latest.json`은 경기 있는 날만 쓴다(기존대로).
- **되감기 범위**: 2026 정규시즌 165개 날짜(03-28~10-12) 전부, 날짜당 파일 1개 + `index.json`. 시범경기·포스트시즌은 넣지 않는다. 선발은 박스스코어 실제 선발(`starter_source: "actual (boxscore pitching order 1)"` 명시) — 예고 선발 이력이 없기 때문.
- **되감기 행과 적중 규칙**: 취소 경기도 `latest.json`과 같은 모양(`home_win_prob: null`, `factors: []`, `result: null`)으로 넣어 165일 모두 파일이 있다(전부 취소된 7일 포함 — 사이트 슬라이더가 날짜를 건너뛰지 않게). `result.pick`은 반올림 전 확률 `>= 0.5`이면 `HOME`(`train_win._correct`와 동일)이고 `correct = pick == winner` — 예: 13572는 표시 0.5000이지만 반올림 전 0.49997이라 pick `AWAY`. 반올림 값으로 판정하면 418/702가 되어 보고서와 어긋난다. LIVE로 멈춘 2경기(13352, 13606)는 제외한다. 출력 확률(`playoff_prob`, `exp_wins`, 시리즈 확률)은 소수 4자리(`OUTLOOK_DIGITS`).
- **되감기 상태**: `rewind.state_before(season, on)`(`date < on`, 2단계 `build_state`를 옮긴 것, `run_pipeline.build_state`는 별칭으로 유지). `build_season`은 상태를 한 번 만들어 날짜마다 그날 경기를 넣기 전에 피처·전망을 계산한다(증분 결과 == `state_before` 테스트).
- **check_parity의 비교 대상**: 6절 "artifacts/py vs artifacts/nb"를 "커밋된 산출물 vs 다시 만든 산출물 + 노트북 내부 assert"로 구체화했다(6절 "4단계 확정"의 표). 계획 시점의 "되감기 샘플 3일"은 Codex 교차 검토 뒤 시즌 전체 165일 + `index.json`(파일 목록 포함)으로 넓혔다.
- **parity는 바이트가 아니라 값**: parquet은 플랫폼 독립 지문(소수 6자리 반올림 CSV의 SHA256, `features_fingerprint`·`matchup_fingerprint`)으로 판정하고 파일 SHA256은 정보로만 찍는다. Linux OpenBLAS와 Windows MKL에서 `features.parquet`의 마지막 비트가 다르기 때문이다(Linux ci 40879259726이 이 한 줄로 실패 → 지문 판정으로 바꾼 뒤 40882643905 성공; 예측 차이 7e-14 이하). 보고서 dict는 상대 오차 1e-9(`abs_tol=0`), 사이트 JSON·CSV·되감기 166파일은 정확히 비교한다. 군집 단계는 맨 마지막에 실행한다 — `threadpool_limits(1)`이 끝난 뒤에도 MKL이 1스레드로 남아(Windows MKL에서 확인) 같은 프로세스의 로지스틱 회귀 마지막 자리가 바뀌는 부작용 때문.
- **얼린 시즌**: report-2026·team-2026·clusters-2026과 하류(사이트 JSON·되감기)는 `FROZEN_SEASONS`(2015~2026)만으로 다시 만들어 비교한다 — 2027 행이 `data/raw`에 쌓여도 매 ci가 실패하지 않게. 라이브 모델은 manifest의 `live.features_fingerprint`가 맞을 때만, 그 번들의 `seasons` 행에서 비교한다.
- **군집 parity(Linux BLAS)**: `cluster compare --against models/clusters.pkl`이 새로 맞춘 번들과 커밋본의 중심(`allclose(rtol=0, atol=1e-9)`, z 공간)·맞춤 시즌 라벨(`(season, player_id)` 외부 병합, 동일)을 비교한다. 주간 워크플로는 compare가 통과할 때만 새 번들을 반영하고, 실패하면 `parity-failure` 이슈를 열고 커밋본을 유지한다.
- **주간 재학습**: `train_win live --skip-if-same`(전 행 예측이 기존 pkl과 `atol 1e-9`로 같고 **그리고** manifest의 `live.features_fingerprint`가 이번 parquet의 지문과 같을 때만 pkl·manifest를 쓰지 않음 — `trained_at` 때문에 매주 바이트가 바뀌는 커밋 노이즈 방지, 지문이 다르면 예측이 같아도 다시 써서 `--require-live` 비교가 건너뛰어지지 않게), `cluster compare --types`(새 유형표 해시가 manifest의 `types_sha256`과 같으면 `types_changed=0` → 통과, 다르면 `types_changed=1` → **실패**: clusters-2026은 얼린 산출물이라 자동으로 다시 맞춰 커밋하지 않고 사람이 원인을 본 뒤 `cluster fit`·`publish`·`train_win report --force`로 다시 얼린다), 전체 `check_parity --require-live`(노트북 02~05 포함, 방금 라이브를 맞췄으므로 라이브 비교 건너뜀도 실패), main에서만 커밋(`git push origin HEAD:main`), 실패 시 `parity-failure` 이슈.
- **박스스코어 재수집**: 현재 시즌 정규시즌 FINAL인데 박스스코어가 없는 경기 중 수집 창(대상일 −7일) **이전** 경기만 최신순 20개를 다시 요청한다(`collect_missing_boxscores(before=…)`). 선발 수집 뒤 별도 try에서 돌고 오류는 `collect_errors`에 남긴다. **얼린 시즌(`FROZEN_SEASONS`, 2015~2026)은 일일 작업이 다시 받지 않는다** — 얼린 산출물(report·team·clusters·되감기)은 지금 박스스코어로 만들어졌고, 새로 받으면 parity가 깨진다(필요하면 사람이 받고 다시 얼린다). 같은 실행에서 수집(`collect_range`·예고 선발)이 예외로 멈췄으면 재수집도 건너뛴다(사이트가 내려가 있을 때 20 × 5초를 더 쓰지 않게). `daily.yml`은 30분 제한.
- **한글 이름 투표**: `player_stats.korean_names`는 정규시즌 FINAL 경기의 박스스코어(`_season_boxes`, 집계표와 같은 경기)만 센다. 일일 작업이 계속 쌓는 포스트시즌·시범경기 기록표가 얼린 이름표를 바꾸지 않게 — 이 변경으로 `players.json`·`teams.json`·`cluster_quality`는 바뀌지 않았다(바뀐 46명은 유형이 없는 선수, parity 확인). 오늘 경기가 없으면 예고 선발 요청을 생략한다. 공개 파일(`_write_json`·`_write_history`)·`games.jsonl`·`starters.jsonl`은 임시 파일 + `os.replace`로 원자적으로 쓴다.
- **노트북 05**: `TARGET`은 2026-10-29로 고정한다(저장된 예고 선발이 있는 날 — 실행 날짜와 무관하게 같은 결과). 로직은 `src/`·`scripts/` 호출만 하고(시리즈 단계도 공개 함수 `simulate.active_series`·`series_record`·`left_homes`·`series_probs`), 패리티는 `run_pipeline.run(fetch=False)`을 임시 폴더에 실행한 `latest.json`(경기 항목·`outlook`)과, 다시 만든 2026-09-01 되감기와 커밋된 `rewind/2026/2026-09-01.json`을 비교한다.
- **numpy 2 전환**: 하지 않는다. 로컬 anaconda(1.26.4)와 Actions의 고정 버전이 같은 것이 더 중요하다(14절).
- **이월 항목 중 이번에 처리**: requirements-dev 분리, 노트북 실행 테스트 `slow` 마커, 경기 없는 날 `fetch_starters` 생략, 현재 시즌 FINAL인데 박스스코어 없는 경기 재수집, 공개 파일 원자적 쓰기, `predict.py` docstring "피처 수 + 1", 주간 재학습에 군집 재계산 비교 포함(처음에는 유형표가 바뀌면 `cluster fit`·`publish`까지 자동으로 했으나, 최종 수정 라운드에서 "바뀌면 실패 — 사람이 다시 얼린다"로 바꿨다), Linux BLAS 군집 비교. 나머지는 이월 문서에 남겼다.
- **알려진 한계(8절 대비) → 해결**: 처음 구현은 시리즈 시뮬레이션이 오늘 경기도 선발 없는 팀 모델로 값을 매겼다(2026-10-29 3차전 SS 49.7% vs 예측 카드 55.4%). 최종 수정 라운드에서 위 "시리즈의 오늘 경기 확률" 규칙으로 고쳤다(시리즈 SS .5279 → .5579).
- **Codex 교차 검토**: `codex exec`(`--sandbox read-only`)로 시뮬레이션 통계·되감기 누수·parity 범위를 검토했다. 누수(`date < on`)·동률 배점·시리즈 종료 처리·417/702는 맞다고 확인했고, 되감기 parity가 3일만 보고 `index.json`을 보지 않는다는 지적을 반영해 시즌 전체 + `index.json`으로 넓혔다. 주간 워크플로 경로 지적은 오독(군집 fit의 **출력** 경로)이었고, 출력 폴더를 `cluster fit`이 만들도록 했다. 보고서 허용 오차는 `abs_tol=0`으로 좁혔다.

구현하며 확정한 규칙(5단계):

계획 시점의 판정(`docs/superpowers/plans/2026-10-30-stage5-site.md`):

- **완성된 `site/`를 먼저, Genspark 브리프는 그 뒤**: Genspark 확인(fetch·내보내기)이 됐으므로 원안대로 Genspark 제작이 목표지만, 사용자 시간이 드는 제작·피드백 전에 참조 구현을 공개해 둔다. 제작본은 검증을 통과하고 더 마음에 들 때만 교체.
- **차트는 인라인 SVG**: 신뢰도 곡선(막대 + 대각선), 시즌 적중률 누적선, 선수 유형 산점도(PCA x, y), 팀 유형 구성 누적 막대, 요인 막대.
- **2D 지도는 PCA 좌표**(목업의 "UMAP"은 PCA로 표기).
- **`DATA_BASE` 자동 선택 + 캐시 버스트**(9절 확정 사항).
- **되감기 전환**: `mode === "rewind"` → 마지막 날짜 + 슬라이더, `live` → `latest.json` + 되감기 토글.
- **포스트시즌 보정 항목은 요인 카드에 넣지 않는다**(모델 항이 아님). 요인 카드는 `factors` 5개 그대로.
- **선수 페이지 기본값**: 가장 최근 시즌(2026), 타자, 팀 전체. 선택은 URL 해시(`#b-2026-2949`, 투수는 `p`)로 공유.
- **팀 페이지 기본 시즌 2026**, `model_expected`가 null인 시즌은 "—".
- **라이브 기록 표**는 `history.csv` 전부를 읽어 `model_version`별 적중률. 행이 적으면 "라이브 기록은 2026 포스트시즌부터"를 명시.
- **Genspark 브리프**는 공통 규칙 + 페이지당 프롬프트 하나 + 수락 체크리스트. `site/` 파일을 참조로 첨부해 "구조·데이터 연결 유지, 완성도 높이기"로 요청.
- **내보내기 반영**: `import_site.py`가 허용 밖 외부 스크립트(beacon 등)를 지우고 경로를 점검한 뒤 `check_site.py`를 돌린다.
- **`site/`는 Pages 전용**이며 일일 Actions 커밋 대상이 아니다(`daily.yml`의 `git add data/raw data/public` 그대로).

실행 중 확정한 규칙:

- **핑크 쪽 작은 글자**: 흰 글자 + 핑크(#ff4d8b)는 작은 글씨에서 대비가 모자라므로, 핑크 카드·매치업 핑크 절반의 작은 글자는 ink 글자 + 크림 안쪽 상자(inset)로 쓴다.
- **취소 경기 카드 색은 `--surface-strong`**(#ebe6d6): 6색 순환 밖의 비활성 서피스라 7번째 색 카드 금지에 걸리지 않는다.
- **최근 10경기(`last10`)**: 승 ÷ (승+패) 소수라 승-패 수를 알 수 없다. 0.1 단위로 딱 떨어지고 시즌 승률과 같지 않을 때만 "최근 10경기 7승 3패", 아니면 "최근 승률 .xxx"(추측해 만들지 않음).
- **빈 되감기 목차**: `index.json`의 `dates`가 비어 있으면 화면이 죽지 않고 오류 문구를 보인다. 되감기 날짜 파일을 못 읽으면 그 카드만 오류 + 다시 불러오기.
- **산점도**: `scatter`에 흐리게(`dim`) 옵션과, 다시 그려도 현재 선택을 잃지 않는 `current` 선택 클로저(화면 크기 변경 뒤 선택 유지).
- **시즌 당시 팀 이름**: `teamNameFor(code, season)` + `OLD_TEAM_NAMES`(SK는 2020까지 "SK 와이번스", WO는 2018까지 "넥센"). 팀 코드는 현재 코드로 통일돼 있으므로 이름만 시즌에 맞춘다.
- **순위표 동률 순서**: 코드에 적은 결정전 결과 `TIEBREAK_GAMES`(2021 1위 KT > 삼성, 2024 5위 KT > SSG — 결정전은 정규시즌 성적 미포함, 두 팀 승률이 정확히 같은지 테스트) → 상대 전적(`vs`가 .500이 아닐 때) → 코드순(임의). 어느 규칙으로 정했는지 쌍마다 표 아래 메모로 적는다.
- **상대 전적 격자 색은 .500에서 나뉜다**(위·아래 두 계열 + 숫자 글자).
- **모델 기대 승률 열은 2026에만**(2015~2025는 학습·검증 시즌이라 `model_expected` null).
- **팀 페이지 가을야구 되감기 차트**는 165일 중 7일 간격으로 날짜를 골라(파일 25개 이하) 각 날짜 파일의 `outlook.teams{}.playoff_prob`를 읽는다.
- **유형 이름은 `model_report.json`의 `cluster_quality`**에서 읽는다(팀 페이지가 1.77 MB `players.json`을 받지 않게). 유형 색은 `app.js`의 `TYPE_COLORS` 하나뿐.
- **`players.json` 지연 로딩**: 홈은 나머지를 다 그린 뒤 마지막에 한 번, 선수 페이지는 한 번만 받고 재시도 때도 다시 받지 않는다(실패하면 비우고 다시 시도).
- **`check_site.py` 검사 범위**: 메뉴(4개 순서·이름·`aria-current`)·증거 바·"GitHub에서 보기"·외부 리소스(호스트 정확히 일치 + jsDelivr 경로 접두사, 인라인 `<style>`·`style=`·assets CSS의 `@import`·`url()`, JS `import` 상대 경로, 트래킹 패턴)·상수(파이썬 원본과 같음)·데이터 계약 키 경로·`?fixture=edge`.
- **사이트의 parity — 숫자는 직접 쓰지 않는다**: 노트북과 py가 바이트가 아니라 값으로 같아야 하듯(6절), 사이트의 모든 숫자·연도는 공개 JSON에서 읽고 HTML에 직접 쓰지 않는다. 팀 이름·요인 이름·유형 번호는 파이썬 원본과의 일치를 `check_site.py`가 검사한다.
- **Genspark 내보내기 반영 규칙**(`import_site.py`): zip·폴더·단일 HTML을 받고, 파일 이름 → `<title>` 낱말(성적표·선수·오늘의 경기·팀) → `--as`로 페이지를 정한다. 지금 `site/`를 `artifacts/site-backup-<시각>/`(gitignore)에 백업한 뒤 덮어쓰고(내보내기에 없는 `assets/` 등은 유지), 허용 밖 외부 `<script>`·`<link>`·트래킹 인라인 스크립트를 지우며, `file://`·`/`로 시작하는 경로를 상대 경로로 바꾼다(Pages는 하위 경로 `/2610_KBO_predict/`). `.json` 등 사이트 파일이 아닌 것은 반영하지 않는다. `check_site --strict`가 실패하면 백업으로 복원(`--keep`이면 남김), `--dry-run`은 임시 복사본에서만.

## 14. 열린 위험

| 위험 | 대응 |
|---|---|
| MyKBOStats 마크업이 바뀌거나 Cloudflare가 자동 요청을 막음 | 파서가 미인식 상태에서 즉시 예외(조용한 오분류 금지). 수집 실패 시 파이프라인은 저장된 데이터로 계속 진행하고 status.json만 갱신. 1단계에서 실패 시 이슈 자동 생성 추가. |
| MyKBOStats 박스스코어에 2B/3B/SB 없음 | **해결 (2026-10-29)**: 경기 페이지 하단 기록표에서 읽어 박스스코어 타자 행에 보탰다(로컬 캐시 9,362경기 재파싱, 기존 칸 불변). 남은 위험: 지표 라벨 미매칭 127건, 캐시 없는 18경기는 None. |
| 선수 한글 이름 소스 없음 (MyKBOStats는 로마자만) | **해결 (2026-10-29)**: 기록표의 한글 `title` 속성 + 시즌별 투표(3표 이상인 가장 최근 시즌의 60% 다수 이름 — 개명 선수는 최근 이름; 1,604명), 개명 선수는 별칭 추론(31명, `data/raw/name_aliases.json`). 남은 위험: 일일 수집은 한글 이름 힌트·별칭 없이 파싱한다. |
| 경기 전 예상 선발 소스 없음 | **해결 (2026-10-29)**: MyKBOStats 예정 경기 페이지의 "Starting pitchers" 섹션. 남은 위험: 정규시즌 예정 경기 페이지에도 같은 섹션이 있는지는 2027 개막 전 확인 필요(확인한 픽스처는 포스트시즌 페이지). |
| Genspark가 외부 JSON fetch를 막음 | **해결 (2026-10-30)**: 사용자가 Genspark의 외부 JSON `fetch`와 HTML 내보내기를 확인했다. 그래도 빌더가 만든 `site/`를 GitHub Pages로 먼저 공개하고(첫 push 후), Genspark 제작본은 `import_site.py` + `check_site.py --strict`를 통과할 때만 교체한다. 남은 위험: 내보내기에 붙는 Cloudflare beacon 같은 외부 스크립트(반영 스크립트가 지움), 트래킹이 아닌 외부 파일(예: Tailwind CDN)을 지우면 스타일이 깨질 수 있어 화면 확인 필요. |
| raw.githubusercontent.com CDN 캐시(최대 5분) | 사이트는 매일 바뀌는 4개 파일(`status.json`·`latest.json`·`history.csv`·`rewind/2026/index.json`)에 `?v=<Date.now()>` + `no-store`를 쓰고, 푸터 증거 바는 `status.json` 기준, 홈 카드는 `latest.json`의 `generated_at`을 작게 함께 적는다. 일일 실행 직후 몇 분은 파일끼리 시각이 어긋나거나 이전 값이 보일 수 있다. |
| GitHub Pages가 저장소에서 아직 꺼져 있음 | `GITHUB_TOKEN`으로는 Pages 사이트를 만들 수 없다(`configure-pages`의 `enablement: true`도 권한 부족으로 실패). 저장소 Settings → Pages에서 Source = GitHub Actions로 push 전에 켜 두고, 첫 `pages.yml` 실행(`site/**` push 또는 수동 실행)이 배포한다. 첫 배포가 끝나기 전에는 URL이 404. |
| 포스트시즌이 곧 끝나 라이브 데이터가 거의 없음 | 0단계 수직 슬라이스로 남은 경기라도 기록. 되감기 모드가 비시즌 메인 콘텐츠, 라이브는 "증거" 역할. |
| v0.1 급조 모델의 예측이 공개 히스토리에 남음 | `history.csv`에 `model_version` 컬럼. 성적표는 버전별로 분리 표시. README에 개선 이력. |
| 노트북 실행 시간이 길어 CI가 느림 | 노트북은 `data/processed/` 스냅샷을 읽도록 하고, 수집 노트북(01)은 parity 대상에서 제외하거나 샘플 날짜만 실행. **→ 4단계**: 노트북 실행 테스트는 `slow` 마커, ci는 `check_parity --quick`(노트북 제외, Windows 약 37초)이고 노트북 02~05는 주간 재학습의 전체 `check_parity`(약 100초, Linux)와 `pytest -m slow`로 돌린다. 01은 parity에서 뺐다. |
| 플랫폼마다 BLAS·libm이 달라 산출물 바이트가 다름 (Linux OpenBLAS vs Windows MKL) | **대응 (4단계)**: parity는 바이트가 아니라 값으로 판정한다 — parquet은 소수 6자리 값 지문, 보고서는 상대 오차 1e-9, 군집은 중심 1e-9·라벨 동일, 파일 SHA256은 정보로만(6절). Linux ci에서 `features.parquet` 바이트만 달랐고(40879259726) 지문 판정으로 통과(40882643905). 군집은 커밋된 `models/clusters.pkl`이 기준. 남은 위험: 어떤 값이 6자리 반올림 경계에 걸리면 플랫폼에 따라 지문이 달라질 수 있다. 같은 프로세스에서 군집 뒤 LR을 학습하면 MKL 스레드 수 때문에 마지막 자리가 바뀐다(check_parity는 군집을 마지막에 실행). |
| numpy 2 전환 | **결정 (4단계): 전환하지 않는다(numpy 1.26.4 유지).** 로컬 anaconda(1.26.4)와 Actions의 `==` 고정 버전이 같아야 parity가 같은 숫자를 낸다. `pyarrow==19.0.1`·`lightgbm==4.7.0`도 numpy 1.x와 호환되는 버전으로 고정. 전환은 로컬 환경을 함께 바꿀 때 한 번에(전환하면 parquet 지문·보고서·되감기를 다시 확인). |
| 포스트시즌 대진표를 사람이 갱신 (`config/postseason.yaml`) | 갱신하지 않으면 그 시리즈는 `next_game` 카드로 떨어질 뿐 파이프라인은 실패하지 않는다(테스트). 2026 한국시리즈 상대는 플레이오프가 끝나면 채운다. |
