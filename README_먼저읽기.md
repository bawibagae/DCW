# 더치페이 수정본 — 적용 전 읽어 주세요

## 구성
- main.py: Android/PC Kivy 앱 (기존 UI 기반 수정)
- server.py: 입력 검증과 OCR을 모두 포함한 Flask 서버
- index.html: 공유 링크 웹 페이지
- requirements.txt: 서버용 / requirements-app.txt: PC 앱용
- Python 파일은 main.py와 server.py 두 개뿐입니다. 테스트 코드는 배포 ZIP에서 제외했습니다.
- file_paths.xml 및 extra_manifest_application.xml: Android FileProvider 리소스
- buildozer.spec.example: 기존 spec에 반영할 예시. 실제 APK 빌드 검증본이 아닙니다.

## 반드시 먼저
1. 이전에 공유한 Google 서비스 계정 키를 폐기하고 새 키를 발급하세요. 이 ZIP에는 키가 없습니다.
2. 운영 DB를 백업하세요. 기존 DB를 삭제하지 않습니다. 테이블 두 개를 추가하지만 기존 금액 오류와 잘못된 입금 상태를 자동 복구하지는 않습니다.
3. 서버/웹/앱을 함께 업데이트하세요. 예전 앱은 request_id가 없어 새 정산 생성에 실패합니다.

## 기존 Render 서비스에 적용
새 서비스를 만들 필요 없이 기존 연결 저장소의 파일을 교체합니다.
서버 배포에는 server.py, index.html, requirements.txt가 필요합니다.
Build Command: pip install -r requirements.txt
Start Command: gunicorn server:app --bind 0.0.0.0:$PORT --workers 1 --threads 4 --timeout 120
Health Check Path: /api/health
Python 3.11 또는 3.12 환경을 권장합니다. 로컬 API 테스트는 Python 3.13에서 수행했습니다.

Render Environment에 .env.example의 값을 설정하세요. 이 파일을 업로드하는 것만으로 환경변수가 적용되지는 않습니다.
- API_BASE_URL: 실제 Render HTTPS 주소. 현재 코드는 기존 첨부의 https://dcw-6vyo.onrender.com을 기준으로 합니다.
- WEB_URL: https://bawibagae.github.io/DCW-web/ (해당 저장소에도 index.html 교체)
  Render에서 웹도 제공하려면 Render 주소 뒤에 /를 붙여 설정해도 됩니다.
- DB_PATH: /var/data/dutchpay.db
- 영속 디스크를 /var/data에 마운트하세요. 일반 배포 파일시스템만 쓰면 재배포/재시작 시 데이터 보존을 보장할 수 없습니다.
  디스크를 제공하지 않는 플랜에서는 영속 디스크 가능 플랜 또는 별도 DB로 전환해야 합니다.
  이 버전은 SQLite용이며 PostgreSQL 연결 문자열만 넣어서는 작동하지 않습니다.
- 기존 DB 경로를 바꾸면 새 DB로 보입니다. 백업 후 기존 DB를 새 영속 경로로 옮겨야 합니다.
- GOOGLE_APPLICATION_CREDENTIALS: /etc/secrets/google-service-account.json
  Render Secret Files에 새 키를 google-service-account.json 이름으로 등록하세요.
  해당 Google 프로젝트에서 Vision API 활성화, 결제 및 권한 설정이 필요합니다.
- DUTCHPAY_WEBHOOK_SECRET: 무작위 32자 이상. 예: python -c "import secrets; print(secrets.token_urlsafe(48))"
  미설정/짧은 키면 입금 웹훅만 503으로 비활성화됩니다.

주소를 변경한다면 main.py의 기본 API_BASE_URL과 index.html의 API_BASE도 바꾸세요.
공유 URL의 api 쿼리를 믿고 서버를 바꾸지 않도록 웹 API 주소를 고정했습니다.
Render 계정 접근, 설정 변경 및 실제 배포는 이 수정 작업에서 실행하지 않았습니다.

## Android 앱
기존 buildozer.spec는 제공되지 않아 기존 설정을 직접 수정하지 못했습니다.
buildozer.spec.example을 참고하되 기존 package.name/package.domain, 서명키, 버전 코드를 유지/갱신하세요.
표기 API 34는 원래 빌드 환경 기준이며 현재 앱스토어 제출 요건 충족을 뜻하지 않습니다.
Google 키/DB/서버 코드를 APK에 넣지 마세요. google-cloud-vision도 앱 requirements에서 제거하세요.
기존 NanumGothic.ttf/NanumGothicBold.ttf가 있다면 유지하세요. 폰트 파일은 이번 첨부에 없어 ZIP에 없습니다.
PC: pip install -r requirements-app.txt 후 python main.py
Android: 설정 반영 후 buildozer android debug. 실기기에서 카메라/파일선택/권한/한국어 표시를 확인하세요.

## 바뀐 동작
- OCR은 로그인 후 서버에서 수행합니다. 인증키가 없어도 영수증 직접 입력은 가능합니다.
- OCR 결과는 자동 확정하지 않습니다. 품목명 | 수량 | 해당 품목 합계금액 형식으로 수정 후 저장합니다.
- 단가가 아닌 품목 전체 금액을 입력하세요. 할인은 품목 금액에 반영하고 총액을 일치시키세요.
- 원 단위 정수 배분으로 청구액 합계를 보존합니다. 품목 공동 부담 UI는 기존 수량 배분 방식입니다.
- 동명이인은 이메일이 표시되는 친구 버튼 또는 구분한 표시 이름으로 입력합니다.
  공유 페이지에는 참여자 표시 이름이 노출됩니다. 친구 선택 시 이메일도 포함되므로 링크 공유 범위를 제한하세요.
- 세션은 7일 후 만료됩니다. 재로그인이 필요합니다.
- 입력 변경 시 참여자를 재적용하고 수량을 확인해야 합니다.
- 네트워크 재시도에서 같은 request_id를 사용해 정산 중복 생성을 줄입니다.
  응답 유실 후 입력을 바꿔 같은 작업을 재전송하면 기존 정산이 반환될 수 있으므로 내역을 먼저 확인하세요.
- 알림은 앱 실행 중 15초 폴링/로컬 알림입니다. 앱 종료 후 푸시 수신은 구현하지 않았습니다.
- 토스/카카오 버튼은 앱 실행과 계좌 복사 보조 기능입니다. 송금 실행/성공을 보장하지 않습니다.

## 실제 입금 연동 — 자동으로 완성되는 부분이 아닙니다
은행/결제사업자의 인증된 연동 서버가 실제 거래를 검증한 뒤 아래 API를 호출해야 합니다.
POST /api/payments/webhook
Header: X-DutchPay-Secret: 서버에 설정한 키
JSON: {"settlement_id": 123, "participant_id": 456, "amount": 18000, "transaction_id": "provider-unique-transaction"}
participant_id는 정산 생성 응답에서 얻는 참여자 ID입니다. 은행의 송금자 이름만으로 이 ID를 추측하지 마세요.
동일 금액만으로 자동 매칭하지 않고 불일치는 409로 보류합니다. 부분입금/초과입금은 수동 확인 대상입니다.
거래 ID는 결제사업자별 접두사를 붙여 전역 고유하게 전달하세요.
이 웹훅은 신뢰하는 연동 서버 전용입니다. 은행 고유 서명검증, 거래 원장 조회, 본인확인, 실제 계좌 연동은 별도 구현해야 합니다.
브라우저/앱에 웹훅 비밀키를 넣지 마세요.

## 검증 및 남은 범위
통합된 server.py에 대해 별도 테스트 환경에서 기존 12개 API 테스트를 재실행했습니다. 결과는 TEST_RESULTS.txt에 있습니다.
12개 API 테스트: 회원가입/로그인 기반으로 잘못된 입력, 총액 불일치, 사용자 연결, 세션 만료,
로그아웃, 중복 정산, 입금 식별/중복, 공개 응답 필드, CORS, 알림, OCR 인증/입력 검사 등을 검증했습니다.
문법 검사와 로컬 테스트 통과는 전체 실서비스 품질 보증이 아닙니다.
실제 Google OCR 호출, Render 영속 디스크/키 설정, APK 빌드, Android 카메라/레이아웃,
실제 은행 입금/앱 딥링크는 미검증입니다. OCR 정규식은 모든 영수증을 정확히 파싱하지 못하므로 사용자 확인이 필수입니다.
기존 build.log의 직접 실패 구간이 생략되어 APK 빌드 원인을 특정하거나 해결을 보장할 수 없습니다.
운영 공개 전 로그인/OCR 호출 속도 제한, 할당량 경보, 모니터링, 백업 정책도 설정하세요.
