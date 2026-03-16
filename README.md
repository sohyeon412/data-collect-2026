# 한국어 AI Overview 크롤러

## 프로젝트 개요

한국어 질의에서 Google SEO 순위와 AI Overview 인용 간 상관관계를 분석하기 위한 크롤러입니다.
500개의 한국어 쿼리를 구글에 검색해서:
- AI Overview에 인용된 URL
- SEO 상위 10개 URL
- 두 결과의 겹침 비율

을 수집하고 CSV로 저장합니다.

---

## 파일 구조

```
.
├── .github/
│   └── workflows/
│       └── crawler.yml       # 깃액션 자동 실행 워크플로우
├── crawler.py                # 메인 크롤러
├── queries_500.csv           # 수집할 한국어 쿼리 500개
├── requirements.txt          # 파이썬 의존성
├── results.csv               # 수집 결과 (자동 생성됨)
├── progress.json             # 체크포인트 (자동 생성됨)
└── README.md
```

---

## 세팅 방법 (Claude Code가 아래 순서대로 해주세요)

### 1단계: 깃허브 레포 생성 및 파일 업로드

```bash
# 새 레포 초기화
git init
git add .
git commit -m "init: AI Overview crawler"

# 깃허브에 새 레포 만들고 (이름 예: ai-overview-crawler)
git remote add origin https://github.com/{유저명}/{레포명}.git
git branch -M main
git push -u origin main
```

### 2단계: 깃액션 권한 설정

깃허브 레포 → Settings → Actions → General 에서:
- Actions permissions: **Allow all actions** 선택
- Workflow permissions: **Read and write permissions** 선택
- **Save** 클릭

(이 설정 안 하면 크롤러 결과를 깃에 자동 커밋 못 함)

### 3단계: 깃액션 활성화 확인

깃허브 레포 → Actions 탭 → "AI Overview Crawler" 워크플로우 확인
- 매일 한국시간 오전 9시에 자동 실행됨
- 수동 실행: Actions → "AI Overview Crawler" → "Run workflow" 클릭

### 4단계: 첫 실행 테스트 (선택)

Actions 탭에서 수동으로 한 번 돌려보고 results.csv가 잘 생기는지 확인

---

## 실행 방식

### 깃액션 자동 실행 (권장)
- 매일 UTC 00:00 (한국 09:00) 자동 실행
- 한 번 실행에 최대 5시간 50분 동작
- progress.json으로 체크포인트 관리 → 어제 50개 했으면 오늘 51번부터 시작
- 완료된 결과는 자동으로 깃에 커밋됨

### 로컬 실행 (테스트용)
```bash
pip install playwright
playwright install chromium
playwright install-deps chromium
python3 crawler.py
```

---

## 결과 파일 (results.csv) 컬럼 설명

| 컬럼 | 설명 |
|------|------|
| id | 쿼리 번호 |
| query | 검색 쿼리 |
| category | 정의형 / 방법형 / 비교형 / 추천형 / 시사형 |
| has_ai_overview | AI Overview 존재 여부 (True/False) |
| ai_overview_urls | AI Overview 인용 URL 목록 (\| 구분) |
| seo_top10_urls | SEO 상위 10개 URL 목록 (\| 구분) |
| overlap_count | 겹치는 URL 수 |
| overlap_ratio | 겹침 비율 (ai_urls 기준, 0~1) |
| crawled_at | 수집 시각 |

---

## 봇 감지 회피 장치

- 랜덤 User-Agent (5종 풀에서 매 실행마다 선택)
- 랜덤 뷰포트 크기
- 쿼리 사이 18~45초 랜덤 딜레이
- 10개마다 30~90초 추가 휴식
- 랜덤 마우스 이동 / 스크롤 시뮬레이션
- navigator.webdriver 숨김 처리

---

## 주의사항

- 구글 정책상 크롤링이 차단될 수 있음 → 딜레이가 충분히 설정되어 있으나 IP 차단 시 깃액션 IP가 바뀔 때까지 1~2일 대기
- AI Overview는 로그인 상태, 지역, 시간에 따라 다르게 나올 수 있음 → 모든 수집은 비로그인, 한국어(ko-KR), 한국(KR) 기준
- results.csv는 누적 저장됨 → 중간에 지우면 처음부터 다시 수집
- progress.json 지우면 체크포인트 초기화됨 (처음부터 재수집)
