import os
import re
import pandas as pd
import streamlit as st
from google.cloud import vision

# ----------------------------------------------------
# 1. Google Cloud Vision API 인증 설정
# ----------------------------------------------------
KEY_PATH = "front-project-497802-81eb2e26c470.json"
if os.path.exists(KEY_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH

st.set_page_config(page_title="영수증 더치페이 정산기", layout="centered")
st.title("🧾 영수증 메뉴/수량 정밀 정산")


# ----------------------------------------------------
# 2. 음식 메뉴, 수량, 가격 정밀 파싱 함수
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

            # 총액 파싱
            if any(keyword in line_str for keyword in total_keywords):
                numbers = re.findall(r"[\d,]+", line_str)
                if numbers:
                    val = int(numbers[-1].replace(",", ""))
                    if val > detected_total:
                        detected_total = val
                continue

            # 기타 메타데이터 필터링
            if any(k in line_str for k in ignore_keywords):
                continue

            # 1) 패턴 A: [메뉴명] [수량] [가격] 형태 (예: "삼겹살 2 20,000")
            match_three = re.search(r"^(.+?)\s+(\d+)\s+([\d,]+)원?$", line_str)
            
            # 2) 패턴 B: [메뉴명] [가격] 형태 (예: "삼겹살 2인분 20,000")
            match_two = re.search(r"^(.+?)\s+([\d,]+)원?$", line_str)

            if match_three:
                item_name = match_three.group(1).strip()
                item_qty = int(match_three.group(2))
                price_str = match_three.group(3).replace(",", "")
                
                # 가맹점 정보 등 제외
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
                        # 메뉴명에 포함된 수량(예: 2인분, 3개) 추출
                        qty_match = re.search(r"(\d+)\s*(인분|개|병|잔|개입|줄)?", item_name)
                        item_qty = int(qty_match.group(1)) if qty_match else 1
                        
                        items.append({"item": item_name, "price": price, "qty": item_qty})

        if detected_total == 0 and items:
            detected_total = sum(item["price"] for item in items)

        return items, detected_total

    except Exception as e:
        st.error(f"OCR 처리 중 오류가 발생했습니다: {e}")
        return [], 0


# ----------------------------------------------------
# 3. Streamlit UI 및 수량 제한 정산
# ----------------------------------------------------
uploaded_file = st.file_uploader("영수증 이미지를 업로드하세요", type=["jpg", "jpeg", "png"])

if uploaded_file is not None:
    st.image(uploaded_file, caption="업로드된 영수증", use_container_width=True)

    with st.spinner("영수증을 분석하는 중..."):
        items, receipt_total = parse_receipt_items_and_total(uploaded_file.getvalue())

    if not items:
        st.warning("영수증에서 메뉴를 찾지 못했습니다. 예시 데이터를 표시합니다.")
        items = [
            {"item": "삼겹살", "price": 20000, "qty": 2},
            {"item": "된장찌개", "price": 7000, "qty": 1},
            {"item": "소주", "price": 10000, "qty": 2},
        ]
        receipt_total = 37000

    st.subheader("📋 인식된 메뉴 목록")
    display_df = pd.DataFrame([{"메뉴명": i["item"], "가격": f"{i['price']:,}원", "영수증 전체 수량": f"{i['qty']}개"} for i in items])
    st.dataframe(display_df, use_container_width=True)
    st.markdown(f"**영수증 인식 총액:** `{receipt_total:,}원`")

    st.markdown("---")
    st.subheader("1. 정산 참여 인원 설정")
    members_input = st.text_input("참여하는 사람 이름을 쉼표(,)로 구분하여 입력하세요", "철수, 영희, 민수")
    members = [name.strip() for name in members_input.split(",") if name.strip()]

    if members:
        st.subheader("2. 음식별 먹은 인원 및 개수 선택")
        st.caption("남은 수량이 0이 되면 추가 개수 증가 및 신규 선택이 자동으로 비활성화됩니다.")

        member_totals = {member: 0.0 for member in members}

        for idx, entry in enumerate(items):
            item_name = entry["item"]
            price = entry["price"]
            total_max_qty = entry["qty"]

            st.write(f"🍽️ **{item_name}** ({price:,}원 / **전체 총 {total_max_qty}개**)")

            cols = st.columns(len(members))
            
            # 선택된 인원의 수량 추적
            item_shares = {}
            current_allocated_sum = 0

            # 1단계: 현재 입력된 총 개수 파악
            for m_idx, member in enumerate(members):
                if st.session_state.get(f"chk_{idx}_{m_idx}", False):
                    val = st.session_state.get(f"num_{idx}_{m_idx}", 1)
                    current_allocated_sum += val

            # 2단계: 각 인원별 체크박스 및 수량 컨트롤러 생성
            for m_idx, member in enumerate(members):
                with cols[m_idx]:
                    chk_key = f"chk_{idx}_{m_idx}"
                    num_key = f"num_{idx}_{m_idx}"

                    # 남은 수량이 없고 본인이 체크되지 않았다면 체크박스 비활성화
                    is_checked = st.session_state.get(chk_key, False)
                    remaining_for_others = total_max_qty - (current_allocated_sum - (st.session_state.get(num_key, 1) if is_checked else 0))
                    
                    chk_disabled = (remaining_for_others <= 0) and not is_checked

                    is_eaten = st.checkbox(member, value=is_checked, disabled=chk_disabled, key=chk_key)

                    if is_eaten:
                        curr_val = st.session_state.get(num_key, 1)
                        # 다른 사람들이 할당받고 남은 상한선 계산
                        max_allowed = max(1, remaining_for_others)

                        # 수량 선택 (최대치 달성 시 더 이상 늘어나지 않도록 max_value 제한)
                        count = st.number_input(
                            f"{member} 개수",
                            min_value=1,
                            max_value=max_allowed,
                            value=min(curr_val, max_allowed),
                            step=1,
                            key=num_key
                        )
                        item_shares[member] = count

            # 비례 분배 금액 계산
            total_selected_qty = sum(item_shares.values())
            if total_selected_qty > 0:
                st.caption(f"선택 수량: {total_selected_qty} / {total_max_qty}개 (남은 수량: {total_max_qty - total_selected_qty}개)")
                for member, share in item_shares.items():
                    member_totals[member] += (price * (share / total_selected_qty))
            else:
                st.caption("선택된 인원이 없습니다.")

            st.markdown("---")

        # ----------------------------------------------------
        # 4. 정산 결과
        # ----------------------------------------------------
        st.subheader("3. 최종 개인별 정산 금액")

        result_data = []
        calculated_total = 0
        for member, total_price in member_totals.items():
            final_amount = round(total_price)
            result_data.append({"이름": member, "정산 금액": f"{final_amount:,}원"})
            calculated_total += final_amount

        st.table(pd.DataFrame(result_data))
        st.write(f"**계산된 총 정산 금액:** {calculated_total:,}원")

        st.subheader("4. 정산 요청 메시지")
        share_text = "[더치페이 정산 요청]\n"
        for member, total_price in member_totals.items():
            share_text += f"• {member}: {round(total_price):,}원\n"
        share_text += f"\n총액: {receipt_total:,}원"

        st.code(share_text, language="text")