import os
import re
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
# 2. 모바일 반응형 UI & 글자 크기 개선 CSS
# ----------------------------------------------------
st.markdown(
    """
    <meta name="viewport" content="width=device-width, initial-scale=1.0, maximum-scale=1.0, user-scalable=no">
    <style>
    /* 전체 폰트 및 배경 반응형 처리 */
    html, body, [class*="css"] {
        font-size: 16px !important;
        font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    }
    .stApp {
        max-width: 500px;
        margin: 0 auto;
        background-color: #f8f9fa;
        padding-bottom: 80px;
    }
    
    /* 카드 스타일 및 글자 가독성 높이기 */
    .card {
        background: white;
        border-radius: 14px;
        padding: 18px;
        margin-bottom: 14px;
        box-shadow: 0 4px 12px rgba(0,0,0,0.06);
    }
    
    /* 모바일 카메라 입력창 모서리 다듬기 */
    div[data-testid="stCameraInput"] {
        border-radius: 16px;
        overflow: hidden;
        border: 2px solid #3b82f6;
    }
    
    /* 하단 원형 카메라 FAB 버튼 */
    div[data-testid="stColumn"]:has(button[key="btn_camera_fab"]) {
        display: flex;
        justify-content: center;
    }
    
    button[key="btn_camera_fab"] {
        width: 72px !important;
        height: 72px !important;
        border-radius: 50% !important;
        background-color: #3b82f6 !important;
        border: none !important;
        box-shadow: 0 6px 16px rgba(59, 130, 246, 0.4) !important;
        padding: 0 !important;
        display: flex !important;
        justify-content: center !important;
        align-items: center !important;
        margin: 10px auto !important;
    }

    button[key="btn_camera_fab"]:active {
        transform: scale(0.92) !important;
        background-color: #2563eb !important;
    }

    button[key="btn_camera_fab"] p {
        display: none !important;
    }

    button[key="btn_camera_fab"]::before {
        content: "";
        width: 34px;
        height: 34px;
        background-image: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24" fill="none" stroke="white" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M14.5 4h-5L7 7H4a2 2 0 0 0-2 2v9a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V9a2 2 0 0 0-2-2h-3l-2.5-3z"/><circle cx="12" cy="13" r="3"/></svg>');
        background-repeat: no-repeat;
        background-position: center;
        background-size: contain;
        display: block;
    }
    
    /* Input 입력창 글자 크기 확대 */
    input {
        font-size: 16px !important;
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
# 4. OCR 파싱 함수
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
# 5. 네비게이션 헤더
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
    
    st.markdown("### 📋 정산 내역")

    history = st.session_state["history"]
    if not history:
        st.info("아직 더치페이 내역이 없습니다.")
    else:
        for item in reversed(history):
            st.markdown(
                f"""
                <div class="card">
                    <div style="font-weight:bold; font-size:17px; color:#111;">{item['date']} 정산</div>
                    <div style="color:#555; font-size:15px; margin-top:4px;">총액: <b>{item['total']:,}원</b> ({len(item['members'])}명)</div>
                    <div style="color:#666; font-size:14px; margin-top:4px;">참여자: {', '.join(item['members'])}</div>
                </div>
                """,
                unsafe_allow_html=True
            )

    st.markdown("---")
    
    col_l, col_btn, col_r = st.columns([1, 1, 1])
    with col_btn:
        if st.button("", key="btn_camera_fab"):
            st.session_state["page"] = "camera"
            st.rerun()


# ====================================================
# [PAGE 2] 로그인 화면
# ====================================================
elif st.session_state["page"] == "login":
    render_header()
    st.markdown("### 🔑 로그인")

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
    st.markdown("### 📝 회원가입")

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
        st.markdown("### 👤 마이페이지")
        st.markdown(
            f"""
            <div class="card">
                <div style="font-size:18px; font-weight:bold;">{user['name']} 님</div>
                <div style="color:#666; font-size:14px; margin-top:4px;">{user['email']}</div>
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
# [PAGE 5] 영수증 촬영 화면 (모바일 카메라 지원 강화)
# ====================================================
elif st.session_state["page"] == "camera":
    render_header()
    st.markdown("### 📸 영수증 스캔")

    # [옵션 1] 테스트용 샘플 버튼
    if st.button("🧪 [테스트] 샘플 영수증으로 바로 테스트", type="primary", use_container_width=True):
        st.session_state["items"] = [
            {"item": "삼겹살 2인분", "price": 36000, "qty": 2},
            {"item": "차돌된장찌개", "price": 8000, "qty": 1},
            {"item": "공기밥", "price": 2000, "qty": 2},
            {"item": "음료수", "price": 2000, "qty": 1}
        ]
        st.session_state["receipt_total"] = 48000
        st.session_state["page"] = "settle"
        st.rerun()

    st.markdown("---")

    # 탭 구성: 실시간 촬영 vs 핸드폰 갤러리/카메라 앱 사용
    tab_cam, tab_file = st.tabs(["📱 모바일 카메라 촬영", "📁 갤러리에서 사진 올리기"])

    image_bytes = None

    with tab_cam:
        st.caption("💡 브라우저 권한 요청 시 '허용'을 누르면 핸드폰 카메라가 열립니다.")
        camera_image = st.camera_input("영수증 촬영")
        if camera_image is not None:
            image_bytes = camera_image.getvalue()

    with tab_file:
        st.caption("💡 핸드폰 기본 카메라 앱으로 촬영한 선명한 영수증 사진을 선택하세요.")
        uploaded_file = st.file_uploader("영수증 이미지 선택", type=["jpg", "jpeg", "png"])
        if uploaded_file is not None:
            image_bytes = uploaded_file.getvalue()

    # 이미지 분석 처리
    if image_bytes is not None:
        with st.spinner("영수증 글자를 읽는 중입니다..."):
            parsed_items, parsed_total = parse_receipt_items_and_total(image_bytes)

            if parsed_items:
                st.session_state["items"] = parsed_items
                st.session_state["receipt_total"] = parsed_total
                st.session_state["page"] = "settle"
                st.rerun()
            else:
                st.error("⚠️ 영수증 글자를 인식하지 못했습니다. 더 밝은 곳에서 촬영하거나 갤러리 파일 업로드를 이용해 주세요.")

    st.markdown("<br>", unsafe_allow_html=True)
    if st.button("취소 및 돌아가기", use_container_width=True):
        st.session_state["page"] = "home"
        st.rerun()


# ====================================================
# [PAGE 6] 분석 결과 및 정산 화면
# ====================================================
elif st.session_state["page"] == "settle":
    render_header()
    st.markdown("### 🧾 영수증 정산")

    current_items = st.session_state.get("items", [])

    if not current_items:
        st.warning("인식된 영수증 정보가 없습니다. 다시 촬영해 주세요.")
        if st.button("📸 영수증 다시 찍기", type="primary", use_container_width=True):
            st.session_state["page"] = "camera"
            st.rerun()
    else:
        st.markdown("#### 🏦 입금받을 계좌 정보")
        col_bank, col_acc = st.columns([1, 2])
        with col_bank:
            bank_name = st.text_input("은행명", placeholder="예: 토스뱅크", key="bank_input")
        with col_acc:
            account_number = st.text_input("계좌번호", placeholder="예: 100083353659", key="acc_input")

        kakaopay_url = st.text_input("🟡 카카오페이 송금링크 (선택)", placeholder="예: https://qr.kakaopay.com/...", key="kakaopay_input")

        st.markdown("#### 👥 참여자 입력")
        member_input_text = st.text_input("참여자 이름 (쉼표 구분)", value="", placeholder="예: 철수, 영희, 민수")
        members = [m.strip() for m in member_input_text.split(",") if m.strip()]

        st.markdown("---")
        st.markdown(f"#### 📋 인식 총액: **{st.session_state.get('receipt_total', 0):,}원**")
        
        if not members:
            st.info("💡 정산에 참여할 사람의 이름을 위에 먼저 입력해 주세요.")
        else:
            member_totals = {m: 0.0 for m in members}
            item_allocated_totals = []

            for idx, item in enumerate(current_items):
                item_name = item["item"]
                price = item["price"]
                max_qty = item["qty"]

                st.write(f"🍽️ **{item_name}** ({price:,}원 / **총 {max_qty}개**)")
                
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

                        is_eaten = st.checkbox(
                            member, 
                            value=is_checked, 
                            disabled=chk_disabled, 
                            key=chk_key
                        )

                        if is_eaten:
                            max_allowed = max(1, remaining_qty)
                            selected_qty = st.number_input(
                                f"{member}", 
                                min_value=1, 
                                max_value=max_allowed, 
                                value=min(st.session_state.get(qty_key, 1), max_allowed), 
                                step=1, 
                                key=qty_key
                            )
                            item_shares[member] = selected_qty

                total_selected_qty = sum(item_shares.values())
                item_allocated_totals.append((total_selected_qty, max_qty))

                if total_selected_qty > 0:
                    for member, share in item_shares.items():
                        member_totals[member] += (price * (share / total_selected_qty))

                st.markdown("---")

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
                        
                        st.markdown(f"**입금 계좌:** `{bank_name} {account_number}`")
                        
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
                        st.markdown("### 💬 카톡방 공유 문구")
                        st.text_area("복사해서 단톡방에 전달하세요:", value=full_share_text, height=180)

                        if st.button("홈으로 이동", use_container_width=True):
                            st.session_state["page"] = "home"
                            st.rerun()

                    show_result_dialog()