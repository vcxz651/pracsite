# Deployment Runbook

이 문서는 Railway 배포와 기본 운영 점검을 **AI 작업자도 반복 가능하게** 만드는 공통 런북이다.

선행 읽기:
1. `docs/project_overview.md`
2. `docs/ai_working_rules.md`
3. 작업 주제가 데모면 `docs/demo_page_plan.md`

원칙:
- 배포 절차는 대시보드 기억이 아니라 **저장소의 배포 설정 파일과 스크립트**를 단일 기준으로 본다.
- 운영 점검은 사람이 감으로 보지 말고, CLI 명령과 확인 포인트를 고정한다.
- 서비스별 도메인 규칙(예: 데모 prewarm)은 해당 기능 SSOT와 함께 본다.

---

## 1. 현재 배포 단일 기준

### 1-1. 웹 시작 명령

- 단일 기준 파일: `Procfile`
- 실제 실행 스크립트: `scripts/release_web.sh`

현재 기준 순서:
1. `manage.py migrate`
2. `manage.py collectstatic --noinput`
3. `gunicorn pracsite.wsgi:application --timeout 120`

의도:
- 배포 후 `/app/staticfiles/` 누락으로 WhiteNoise가 깨지는 일을 줄인다.
- 데모 첫 진입이 무거운 시점에도 기본 30초 timeout보다 여유를 둔다.

주의:
- Railway 대시보드의 Start Command를 별도로 고정했다면, 이 파일과 같은 명령인지 맞춰야 한다.
- 대시보드 명령과 저장소 기준이 다르면, 저장소 문서보다 실제 배포가 먼저 어긋난다.

### 1-2. 데모 prewarm 명령

- 단일 기준 스크립트: `scripts/prewarm_demo.sh`
- 내부 실행: `manage.py prepare_demo_cache`

용도:
- 데모 시나리오 템플릿(A/B/C)을 미리 생성한다.
- 운영 서버에서 `/demo/start/` 첫 진입이 lazy create로 timeout 나는 위험을 낮춘다.

---

## 2. 배포 직후 기본 절차

### 2-1. Railway 재배포 직후

1. `railway status`
2. `railway logs --lines 200`
3. 시작 로그에서 `collectstatic` 출력이 `gunicorn`보다 먼저 있는지 확인
4. `No directory at: /app/staticfiles/` 경고가 없는지 확인

### 2-2. 데모 사전 준비

1. `railway run bash scripts/prewarm_demo.sh`
2. 출력에 `prepared scenario=1`, `prepared scenario=2`, `prepared scenario=3`가 포함되는지 확인
3. 실패 시 `railway logs --lines 200 --filter "demo"` 또는 `railway logs --lines 200 --filter "@level:error"`로 재확인

주의:
- `railway logs`는 로그 스트림이다. 그 창에서 다른 명령을 이어 치지 말고, 필요 시 `Ctrl + C`로 먼저 끊는다.
- `railway run`은 원격 컨테이너 셸이 아니라 **Railway 환경변수로 로컬 명령을 실행**하는 방식이다.
- 따라서 원격 컨테이너 내부 상태는 `railway logs`와 실제 서비스 응답으로 확인한다.

---

## 3. 운영 점검 기본 세트

### 3-1. 애플리케이션 응답

1. `curl -I -L --max-time 20 https://pracsite-production.up.railway.app/`
2. 상태 코드 `200` 확인
3. 데모 홈(`https://pracsite-production.up.railway.app/demo/`)도 브라우저 또는 `curl`로 확인

### 3-2. Django 기본 점검

1. `railway run ./.venv/bin/python manage.py check`
2. 필요 시 `railway run ./.venv/bin/python manage.py collectstatic --noinput`

설명:
- `railway run`은 production 환경변수를 주입하므로, 배포 환경 변수 기준으로 로컬 검증할 수 있다.
- 단, 실제 배포 프로세스가 무엇을 실행했는지까지 보장하지는 않는다.

### 3-3. 장애 확인

1. `railway logs --lines 200`
2. `railway logs --lines 200 --filter "@level:error"`
3. 데모 장애면 `railway logs --since 30m --filter "demo OR WORKER TIMEOUT"`

빠른 판단:
- `WORKER TIMEOUT`이면 요청 자체가 너무 무겁거나 gunicorn timeout이 부족한 것
- `No directory at: /app/staticfiles/`면 `collectstatic` 미적용 가능성
- `Missing staticfiles manifest entry`면 정적 파일 수집/배포 누락 가능성

---

## 4. Supabase 확인 범위

원칙:
- 현재 프로젝트의 장애 원인 확인은 **Railway 앱 로그가 우선**이다.
- Supabase 로그는 DB 레벨 신호만 보여주므로, Django traceback 대체재로 쓰지 않는다.

현재 확인 가능한 범위:
- Supabase CLI가 설치돼 있으면 `inspect db ...` 계열로 long-running query, locks, calls 같은 DB 상태 점검 가능
- Railway처럼 hosted app logs를 CLI로 바로 tail하는 흐름은 현재 운영 기준에서 기본 경로로 두지 않는다

판단 규칙:
- 앱 500, timeout, 템플릿 렌더링, static 문제: Railway 로그 먼저
- DB 락/느린 쿼리 의심: Supabase 보조 확인

---

## 5. AI 의존형 운영 원칙

1. 대시보드 수동 기억보다 `Procfile`, `scripts/`, `docs/`를 먼저 읽게 만든다.
2. 배포 명령, prewarm 명령, 검증 명령을 짧은 고정 커맨드로 유지한다.
3. 장애 대응 시 "느낌상"이 아니라 `logs`, `curl`, `manage.py check` 결과로 판단한다.
4. 새 배포 리스크가 확인되면 기능 handoff 문서가 아니라 이 문서와 관련 SSOT에 바로 반영한다.

현재 프로젝트에서 AI가 먼저 확인할 기본 순서:
1. `railway status`
2. `railway logs --lines 200`
3. `curl -I -L --max-time 20 https://pracsite-production.up.railway.app/`
4. `railway run ./.venv/bin/python manage.py check`
5. 데모 이슈면 `railway run bash scripts/prewarm_demo.sh`

---

## 6. 문서 연계

- 데모 timeout/prewarm 정책: `docs/demo_page_plan.md`
- 공통 AI 가드레일: `docs/ai_working_rules.md`
- 프로젝트 구조/진입점: `docs/project_overview.md`
