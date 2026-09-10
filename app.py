import os
import re
import base64
import datetime
import urllib.parse
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from google.cloud import vision

# ----------------------------------------------------
# 1. Google Cloud Vision API 인증 및 기본 설정
# ----------------------------------------------------
KEY_PATH = "front-project-497802-81eb2e26c470.json"
if os.path.exists(KEY_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH

st.set_page_config(
    page_title="영수증 더치페이",
    page_icon="🧾",
    layout="centered",
    initial_sidebar_state="collapsed"
)

# ----------------------------------------------------
# 2. 모바일 강제 가독성 CSS (WebKit 오버라이드 및 폰트 크기/색상 고정)
# ----------------------------------------------------
st.markdown(
    """
    <style>
    /* Streamlit 전체 텍스트 강제 적용 */
    html, body, [class*="css"], [data-testid="stMarkdownContainer"] p, span, label, div {
        color: #000000 !important;
        opacity: 1 !important;
        visibility: visible !important;
    }

    /* 입력창 내부/외부 텍스트 고정 */
    input, textarea, select {
        color: #000000 !important;
        background-color: #ffffff !important;
        border: 1px solid #cccccc !important;
        -webkit-text-fill-color: #000000 !important;
        opacity: 1 !important;
    }

    /* 체크박스 글자 안보임 문제 강제 해결 */
    [data-testid="stCheckbox"] span {
        color: #000000 !important;
        font-weight: bold !important;
        font-size: 16px !important;
    }

    /* st.number_input 내부 수량 글자 강제 지정 */
    [data-testid="stNumberInput"] input {
        color: #000000 !important;
        font-weight: bold !important;
        background-color: #f0f2f6 !important;
    }

    /* 카드 스타일 */
    .card {
        background-color: #ffffff !important;
        border: 2px solid #e0e0e0 !important;
        border-radius: 12px;
        padding: 16px;
        margin-bottom: 12px;
    }
    .card-title {
        font-weight: bold;
        font-size: 18px;
        color: #000000 !important;
    }
    .card-sub {
        font-size: 14px;
        color: #444444 !important;
    }
    </style>
    """,
    unsafe_allow_html=True
)

# ----------------------------------------------------
# 3. 세션 상태 초기화
# ----------------------------------------------------
if "page" not in st.session_state:
    st.session_state["page"] = "home"
if "users_db" not in st.session_state:
    st.session_state["users_db"] = {}
if "current_user" not in st.session_state:
    st.session_state["current_user"] = None
if "history" not in st.session_state:
    st.session_state["history"] = []
if "items" not in st.session_state:
    st.session_state["items"] = []
if "receipt_total" not in st.session_state:
    st.session_state["receipt_total"] = 0


# ----------------------------------------------------
# 4. OCR 파싱 함수 (Google Cloud Vision API)
# ----------------------------------------------------
def parse_receipt_items_and_total(image_bytes):
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)

        response = client.text_detection(image=image)
        texts = response.text_annotations

        if not texts:
            return [], 0

        full_text = texts[0].description
        lines = full_text.split("\n")

        items = []
        detected_total = 0

        ignore_keywords = [
            "등록", "POS", "pos", "포스", "일시", "날짜", "시간", "점포", 
            "가맹점", "사업자", "대표", "TEL", "Tel", "tel", "주소", 
            "승인", "카드", "현금", "VAT", "vat", "부가세", "TAX", "tax", 
            "테이블", "주문", "영수증", "BILL", "Bill", "전표", "고객"
        ]

        total_keywords = ["합계", "총액", "총결제금액", "결제금액", "받을금액", "TOTAL", "Total"]

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if any(keyword in line_str for keyword in total_keywords):
                numbers = re.findall(r"[\d,]+", line_str)
                if numbers:
                    val = int(numbers[-1].replace(",", ""))
                    if val > detected_total:
                        detected_total = val
                continue

            if any(k in line_str for k in ignore_keywords):
                continue

            match_three = re.search(r"^(.+?)\s+(\d+)\s+([\d,]+)원?$", line_str)
            match_two = re.search(r"^(.+?)\s+([\d,]+)원?$", line_str)

            if match_three:
                item_name = match_three.group(1).strip()
                item_qty = int(match_three.group(2))
                price_str = match_three.group(3).replace(",", "")
                
                if not any(k in item_name for k in ignore_keywords) and price_str.isdigit():
                    price = int(price_str)
                    if 500 <= price <= 1000000:
                        items.append({"item": item_name, "price": price, "qty": item_qty})

            elif match_two:
                item_name = match_two.group(1).strip()
                price_str = match_two.group(2).replace(",", "")
                item_name_cleaned = re.sub(r"[\[\]\(\)\{\}\:\-\=\.\,]", "", item_name).strip()
                
                if item_name_cleaned.isdigit() or len(item_name_cleaned) == 0:
                    continue

                if price_str.isdigit():
                    price = int(price_str)
                    if 500 <= price <= 1000000:
                        qty_match = re.search(r"(\d+)\s*(인분|개|병|잔|개입|줄)?", item_name)
                        item_qty = int(qty_match.group(1)) if qty_match else 1
                        items.append({"item": item_name, "price": price, "qty": item_qty})

        if detected_total == 0 and items:
            detected_total = sum(item["price"] for item in items)

        return items, detected_total

    except Exception as e:
        st.error(f"OCR 분석 중 오류가 발생했습니다: {e}")
        return [], 0


# ----------------------------------------------------
# 5. 상단 헤더
# ----------------------------------------------------
def render_header():
    col_logo, col_user = st.columns([2, 1])
    with col_logo:
        if st.button("🧾 DutchPay", key="btn_home_logo"):
            st.session_state["page"] = "home"
            st.rerun()

    with col_user:
        if st.session_state["current_user"]:
            if st.button("👤 마이페이지", key="btn_mypage_nav"):
                st.session_state["page"] = "mypage"
                st.rerun()
        else:
            if st.button("🔑 로그인", key="btn_login_nav"):
                st.session_state["page"] = "login"
                st.rerun()


# ====================================================
# [PAGE 1] 홈 화면
# ====================================================
if st.session_state["page"] == "home":
    render_header()
    
    st.markdown("<h3 style='color:#000000;'>📋 정산 내역</h3>", unsafe_allow_html=True)

    history = st.session_state["history"]
    if not history:
        st.info("아직 더치페이 내역이 없습니다.")
    else:
        for item in reversed(history):
            st.markdown(
                f"""
                <div class="card">
                    <div class="card-title">{item['date']} 정산</div>
                    <div class="card-sub">총액: <b>{item['total']:,}원</b> ({len(item['members'])}명)</div>
                    <div class="card-sub">참여자: {', '.join(item['members'])}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    st.markdown("---")
    
    if st.button("📸 영수증 스캔하러 가기", type="primary", use_container_width=True):
        st.session_state["page"] = "camera"
        st.rerun()


# ====================================================
# [PAGE 2] 로그인 화면
# ====================================================
elif st.session_state["page"] == "login":
    render_header()
    st.markdown("<h3 style='color:#000000;'>🔑 로그인</h3>", unsafe_allow_html=True)

    email = st.text_input("이메일", placeholder="example@email.com")
    password = st.text_input("비밀번호", type="password")

    if st.button("로그인", type="primary", use_container_width=True):
        users = st.session_state["users_db"]
        if email in users and users[email]["password"] == password:
            st.session_state["current_user"] = {
                "email": email,
                "name": users[email]["name"]
            }
            st.success(f"{users[email]['name']}님 환영합니다!")
            st.session_state["page"] = "home"
            st.rerun()
        else:
            st.error("이메일 또는 비밀번호가 일치하지 않습니다.")

    st.markdown("---")
    if st.button("회원가입 하러가기", use_container_width=True):
        st.session_state["page"] = "signup"
        st.rerun()


# ====================================================
# [PAGE 3] 회원가입 화면
# ====================================================
elif st.session_state["page"] == "signup":
    render_header()
    st.markdown("<h3 style='color:#000000;'>📝 회원가입</h3>", unsafe_allow_html=True)

    name = st.text_input("이름", placeholder="홍길동")
    email = st.text_input("이메일", placeholder="example@email.com")
    password = st.text_input("비밀번호", type="password")

    if st.button("가입완료", type="primary", use_container_width=True):
        if not name or not email or not password:
            st.warning("모든 항목을 입력해 주세요.")
        elif email in st.session_state["users_db"]:
            st.error("이미 가입된 이메일입니다.")
        else:
            st.session_state["users_db"][email] = {
                "password": password,
                "name": name
            }
            st.success("회원가입이 완료되었습니다! 로그인해 주세요.")
            st.session_state["page"] = "login"
            st.rerun()


# ====================================================
# [PAGE 4] 마이페이지 화면
# ====================================================
elif st.session_state["page"] == "mypage":
    render_header()
    user = st.session_state["current_user"]

    if user:
        st.markdown("<h3 style='color:#000000;'>👤 마이페이지</h3>", unsafe_allow_html=True)
        st.markdown(
            f"""
            <div class="card">
                <div class="card-title">{user['name']} 님</div>
                <div class="card-sub">{user['email']}</div>
            </div>
            """,
            unsafe_allow_html=True
        )

        if st.button("로그아웃", use_container_width=True):
            st.session_state["current_user"] = None
            st.session_state["page"] = "home"
            st.rerun()
    else:
        st.session_state["page"] = "login"
        st.rerun()


# ====================================================
# [PAGE 5] 카메라 호출
# ====================================================
elif st.session_state["page"] == "camera":
    render_header()

    if st.button("🧪 [테스트] 샘플 영수증으로 바로 정산하기", type="primary", use_container_width=True):
        st.session_state["items"] = [
            {"item": "삼겹살 2인분", "price": 36000, "qty": 2},
            {"item": "차돌된장찌개", "price": 8000, "qty": 1},
            {"item": "공기밥", "price": 2000, "qty": 2},
            {"item": "음료수", "price": 2000, "qty": 1}
        ]
        st.session_state["receipt_total"] = 48000
        st.session_state["page"] = "settle"
        st.rerun()

    st.markdown("<br>", unsafe_allow_html=True)

    cam_html = """
    <!DOCTYPE html>
    <html>
    <head>
        <style>
            body { margin: 0; padding: 0; display: flex; justify-content: center; align-items: center; background: transparent; }
            .cam-container { display: flex; justify-content: center; align-items: center; padding: 10px 0; }
            .cam-button {
                width: 90px; height: 90px; border-radius: 50%; background-color: #3b82f6;
                display: flex; justify-content: center; align-items: center; cursor: pointer;
                box-shadow: 0 8px 24px rgba(59, 130, 246, 0.4);
            }
            input[type="file"] { display: none; }
        </style>
    </head>
    <body>
        <div class="cam-container">
            <label for="native_camera" class="cam-button">
                <svg width="44" height="44" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">
                    <path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/>
                    <circle cx="12" cy="13" r="3"/>
                </svg>
            </label>
            <input type="file" id="native_camera" accept="image/*" capture="environment" onchange="handleFile(this)">
        </div>
        <script>
            function handleFile(input) {
                if (input.files && input.files[0]) {
                    const reader = new FileReader();
                    reader.onload = function(e) {
                        const base64Data = e.target.result.split(',')[1];
                        window.parent.postMessage({ type: 'CAMERA_CAPTURED', image: base64Data }, '*');
                    };
                    reader.readAsDataURL(input.files[0]);
                }
            }
        </script>
    </body>
    </html>
    """

    components.html(cam_html, height=130)

    uploaded_file = st.file_uploader("", type=["jpg", "jpeg", "png"], label_visibility="collapsed")
    
    image_bytes_to_process = None
    if uploaded_file is not None:
        image_bytes_to_process = uploaded_file.getvalue()

    if image_bytes_to_process:
        with st.spinner("영수증 글자를 읽는 중입니다..."):
            parsed_items, parsed_total = parse_receipt_items_and_total(image_bytes_to_process)

            if parsed_items:
                st.session_state["items"] = parsed_items
                st.session_state["receipt_total"] = parsed_total
                st.session_state["page"] = "settle"
                st.rerun()
            else:
                st.error("⚠️ 영수증 글자를 인식하지 못했습니다. 더 밝고 선명한 곳에서 촬영해 주세요.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("취소 및 홈으로", use_container_width=True):
        st.session_state["page"] = "home"
        st.rerun()


# ====================================================
# [PAGE 6] 정산 화면 (글자 안보임 문제 원천 수정)
# ====================================================
elif st.session_state["page"] == "settle":
    render_header()
    
    # 순수 HTML 렌더링으로 글자 강제 표기
    st.markdown("<h3 style='color:#000000 !important; font-weight:bold;'>🧾 영수증 정산</h3>", unsafe_allow_html=True)

    current_items = st.session_state.get("items", [])

    if not current_items:
        st.warning("인식된 영수증 정보가 없습니다. 다시 스캔해 주세요.")
        if st.button("📸 영수증 다시 찍기", type="primary", use_container_width=True):
            st.session_state["page"] = "camera"
            st.rerun()
    else:
        st.markdown("<h4 style='color:#000000 !important;'>🏦 입금받을 계좌 정보</h4>", unsafe_allow_html=True)
        col_bank, col_acc = st.columns([1, 2])
        with col_bank:
            bank_name = st.text_input("은행명", placeholder="예: 토스뱅크", key="bank_input")
        with col_acc:
            account_number = st.text_input("계좌번호", placeholder="예: 100083353659", key="acc_input")

        kakaopay_url = st.text_input("🟡 카카오페이 송금링크 (선택)", placeholder="예: https://qr.kakaopay.com/...", key="kakaopay_input")

        st.markdown("<h4 style='color:#000000 !important;'>👥 참여자 입력</h4>", unsafe_allow_html=True)
        member_input_text = st.text_input("참여자 이름 (쉼표 구분)", value="", placeholder="예: 철수, 영희, 민수")
        members = [m.strip() for m in member_input_text.split(",") if m.strip()]

        st.markdown("---")
        
        total_val = st.session_state.get('receipt_total', 0)
        st.markdown(f"<div style='font-size:18px; color:#000000 !important; font-weight:bold;'>📋 인식 총액: <span style='color:#0064FF;'>{total_val:,}원</span></div><br>", unsafe_allow_html=True)
        
        if not members:
            st.info("💡 정산에 참여할 사람의 이름을 위에 먼저 입력해 주세요.")
        else:
            member_totals = {m: 0.0 for m in members}
            item_allocated_totals = []

            for idx, item in enumerate(current_items):
                item_name = item["item"]
                price = item["price"]
                max_qty = item["qty"]

                # 메뉴 이름 및 가격 HTML 강제 표기
                st.markdown(
                    f"""
                    <div style='background-color:#f8f9fa; padding:10px; border-radius:8px; margin-bottom:8px; border-left:4px solid #3b82f6;'>
                        <span style='color:#000000 !important; font-size:16px; font-weight:bold;'>🍽️ {item_name}</span>
                        <span style='color:#555555 !important; font-size:14px;'> ({price:,}원 / 총 {max_qty}개)</span>
                    </div>
                    """, 
                    unsafe_allow_html=True
                )
                
                allocated_sum = 0
                for m_idx, member in enumerate(members):
                    chk_key = f"chk_{idx}_{m_idx}"
                    qty_key = f"qty_{idx}_{m_idx}"
                    if st.session_state.get(chk_key, False):
                        allocated_sum += st.session_state.get(qty_key, 1)

                cols = st.columns(len(members))
                item_shares = {}

                for m_idx, member in enumerate(members):
                    with cols[m_idx]:
                        chk_key = f"chk_{idx}_{m_idx}"
                        qty_key = f"qty_{idx}_{m_idx}"

                        is_checked = st.session_state.get(chk_key, False)
                        current_user_qty = st.session_state.get(qty_key, 1) if is_checked else 0
                        
                        other_allocated = allocated_sum - current_user_qty
                        remaining_qty = max_qty - other_allocated

                        chk_disabled = (remaining_qty <= 0) and not is_checked

                        # 모바일 브라우저 글자 보임 보장형 라벨 렌더링
                        is_eaten = st.checkbox(
                            member, 
                            value=is_checked, 
                            disabled=chk_disabled, 
                            key=chk_key
                        )

                        if is_eaten:
                            max_allowed = max(1, remaining_qty)
                            selected_qty = st.number_input(
                                "수량", 
                                min_value=1, 
                                max_value=max_allowed, 
                                value=min(st.session_state.get(qty_key, 1), max_allowed), 
                                step=1, 
                                key=qty_key,
                                label_visibility="collapsed" # 모바일에서 중복 라벨로 인해 글자가 증발하는 현상 방지
                            )
                            item_shares[member] = selected_qty

                total_selected_qty = sum(item_shares.values())
                item_allocated_totals.append((total_selected_qty, max_qty))

                if total_selected_qty > 0:
                    for member, share in item_shares.items():
                        member_totals[member] += (price * (share / total_selected_qty))

                st.markdown("<hr style='margin:12px 0; border:0; border-top:1px solid #eee;'>", unsafe_allow_html=True)

            if st.button("⚡ 정산하기", use_container_width=True, type="primary"):
                has_unallocated = any(selected < max_q for selected, max_q in item_allocated_totals)

                if has_unallocated:
                    st.warning("⚠️ 선택되지 않은 메뉴 수량이 있습니다.")
                elif not bank_name or not account_number:
                    st.warning("⚠️ 은행명과 계좌번호를 입력해 주세요.")
                else:
                    final_member_totals = {m: round(amt) for m, amt in member_totals.items()}
                    
                    param_list = [f"{m}:{amt}" for m, amt in final_member_totals.items()]
                    data_param = ",".join(param_list)
                    
                    encoded_data = urllib.parse.quote(data_param)
                    encoded_bank = urllib.parse.quote(bank_name.strip())
                    encoded_acc = urllib.parse.quote(account_number.strip())

                    base_web_url = "https://bawibagae.github.io/DCW-web/"
                    share_url = f"{base_web_url}?data={encoded_data}&bank={encoded_bank}&acc={encoded_acc}"
                    if kakaopay_url:
                        share_url += f"&kakaopay={urllib.parse.quote(kakaopay_url.strip())}"

                    message_lines = ["📢 정산이 완료되었습니다!\n"]
                    for m, amt in final_member_totals.items():
                        message_lines.append(f"• {m}: {amt:,}원")
                    
                    message_lines.append(f"\n🏦 입금계좌: {bank_name} {account_number}")
                    if kakaopay_url:
                        message_lines.append(f"🟡 카카오페이: {kakaopay_url.strip()}")
                    
                    message_lines.append(f"\n🔗 상세 내역 및 송금 링크:\n{share_url}")
                    
                    full_share_text = "\n".join(message_lines)

                    st.session_state["history"].append({
                        "date": datetime.date.today().strftime("%Y-%m-%d"),
                        "total": st.session_state["receipt_total"],
                        "members": members
                    })

                    @st.dialog("최종 정산 결과")
                    def show_result_dialog():
                        result_table = [{"이름": m, "정산 금액": f"{amt:,}원"} for m, amt in final_member_totals.items()]
                        st.table(pd.DataFrame(result_table))
                        
                        st.markdown(f"<p style='color:#000000 !important;'><b>입금 계좌:</b> <code>{bank_name} {account_number}</code></p>", unsafe_allow_html=True)
                        
                        first_amt = list(final_member_totals.values())[0] if final_member_totals else 0
                        pay_html = f"""
                        <div style="font-family: sans-serif; text-align: center; margin-top: 10px;">
                            <button onclick="payToss()" style="
                                width: 100%; padding: 14px; margin-bottom: 8px;
                                background-color: #0064FF; color: white; border: none;
                                border-radius: 10px; font-weight: bold; font-size: 15px; cursor: pointer;">
                                🔹 토스 앱 실행 ({first_amt:,}원 자동 입력)
                            </button>
                            <button onclick="payKakao()" style="
                                width: 100%; padding: 14px;
                                background-color: #FEE500; color: #191919; border: none;
                                border-radius: 10px; font-weight: bold; font-size: 15px; cursor: pointer;">
                                🟡 계좌 복사 후 카카오톡 실행
                            </button>
                        </div>
                        <script>
                        function payToss() {{
                            const b = "{bank_name}";
                            const a = "{account_number}";
                            const amt = "{first_amt}";
                            navigator.clipboard.writeText(b + " " + a);
                            window.top.location.href = `supertoss://send?bank=${{encodeURIComponent(b)}}&accountNo=${{a}}&amount=${{amt}}`;
                        }}
                        function payKakao() {{
                            const acc = "{bank_name} {account_number}";
                            navigator.clipboard.writeText(acc).then(() => {{
                                alert("계좌번호(" + acc + ")가 복사되었습니다!");
                                window.top.location.href = "kakaotalk://";
                            }});
                        }}
                        </script>
                        """
                        components.html(pay_html, height=130)

                        st.markdown("---")
                        st.markdown("<h3 style='color:#000000 !important;'>💬 카톡방 공유 문구</h3>", unsafe_allow_html=True)
                        st.text_area("복사해서 단톡방에 전달하세요:", value=full_share_text, height=180)

                        if st.button("홈으로 이동", use_container_width=True):
                            st.session_state["page"] = "home"
                            st.rerun()

                    show_result_dialog()