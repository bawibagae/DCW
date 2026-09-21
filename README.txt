# 더치페이 수정본

## 파일
- `main_updated.py`: Kivy 앱 본체
- `backend_server.py`: Flask + SQLite 백엔드
- `index_updated.html`: 정산 링크를 받는 웹 페이지
- `requirements.txt`: Python 패키지

## 1. 백엔드 실행

```bash
pip install -r requirements.txt
python backend_server.py
```

기본 주소:
`http://localhost:5000`

배포 서버를 쓸 경우 환경변수:
```bash
API_BASE_URL=https://your-api.example.com
WEB_URL=https://bawibagae.github.io/DCW-web/
```

## 2. 앱에서 백엔드 주소 지정

Android 실기기에서 PC의 로컬 Flask 서버를 테스트할 때는
PC의 사설 IP 주소를 사용해야 합니다.

예:
```bash
API_BASE_URL=http://192.168.0.10:5000
```

Android 에뮬레이터에서는 기본값 `http://10.0.2.2:5000`이 사용됩니다.

## 3. 구현된 기능

- 서버 DB 기반 회원가입/로그인
- 비밀번호 PBKDF2 해시 저장
- 친구 추가/목록
- 이름 입력칸 개별 분리
- `+ 이름 추가`로 참여자 칸 추가
- 친구를 눌러 빈 이름 칸에 바로 추가
- 여러 영수증을 한 정산에 포함
- 정산 시 결과 팝업 제거
- `정산 링크 복사` 버튼을 누르면 링크가 바로 클립보드로 복사
- 공유 웹 페이지에서 참여자별 입금 상태 표시
- 서버의 입금 상태가 바뀌면 앱 알림
- Android에서는 `plyer.notification`을 통한 로컬 알림 시도
- 정산/친구/알림 데이터 서버 저장

## 4. 실제 입금 자동 감지

백엔드에 다음 웹훅이 구현되어 있습니다.

`POST /api/payments/webhook`

헤더:
```text
X-DutchPay-Secret: 설정한 웹훅 비밀키
```

JSON 예:
```json
{
  "settlement_id": 123,
  "amount": 18000,
  "sender_user_id": 7,
  "sender_name": "영희",
  "transaction_id": "bank-tx-20260915-001"
}
```

은행/결제서비스가 이 웹훅을 호출하면 해당 참여자의 상태가 `paid`로 바뀌고,
정산을 만든 사람에게 `payment_received` 알림이 생성됩니다.

중요:
일반 은행 계좌번호만 입력한다고 앱이 은행 거래내역을 자동으로 읽을 수 있는 것은 아닙니다.
실서비스에서는 사용하는 은행/토스/결제대행사의 공식 거래내역 API 또는 웹훅을
이 `/api/payments/webhook`에 연결해야 합니다.

## 5. 보안

`backend_server.py`의 기본 `DUTCHPAY_WEBHOOK_SECRET`는 배포 전에 반드시 변경하세요.
또한 `API_BASE_URL`과 `WEB_URL`도 실제 서버/웹 주소로 변경해야 합니다.


[APK 빌드 참고]
- buildozer.spec는 requests와 Android 13+ POST_NOTIFICATIONS 권한을 포함합니다.
- FileProvider는 android.extra_manifest_application_arguments와 android.res_xml로 연결됩니다.
- file_paths.xml은 FileProvider가 사용할 res/xml 리소스입니다.
- backend_server.py는 APK에 포함된 로컬 앱 서버가 아니라 별도로 배포하는 Flask 백엔드입니다. APK의 API_BASE_URL을 실제 HTTPS 서버 주소로 설정하세요.
- Google 서비스 계정 JSON 키는 APK에 넣지 마세요. 민감한 인증키는 서버에서만 사용하세요.
