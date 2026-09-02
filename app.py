import os
import re
from google.cloud import vision

from kivy.app import App
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.gridlayout import GridLayout
from kivy.uix.scrollview import ScrollView
from kivy.uix.label import Label
from kivy.uix.button import Button
from kivy.uix.textinput import TextInput
from kivy.uix.checkbox import CheckBox
from kivy.uix.popup import Popup
from kivy.uix.filechooser import FileChooserIconView
from kivy.core.window import Window

# ----------------------------------------------------
# 1. Google Cloud Vision API 인증 설정
# ----------------------------------------------------
KEY_PATH = "front-project-497802-81eb2e26c470.json"
if os.path.exists(KEY_PATH):
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = KEY_PATH

# 모바일 화면 크기 시뮬레이션 (PC 테스트용)
Window.size = (360, 680)

# ----------------------------------------------------
# 2. OCR 파싱 함수 (기존 로직 유지)
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
        print(f"OCR Error: {e}")
        return [], 0


# ----------------------------------------------------
# 3. Kivy 모바일 메인 앱
# ----------------------------------------------------
class ReceiptApp(App):
    def build(self):
        self.items = []
        self.receipt_total = 0
        self.members = []
        self.member_inputs = {}  # { (item_idx, member_name): {"chk": CheckBox, "qty": TextInput} }

        # 메인 최상위 레이아웃
        main_layout = BoxLayout(orientation='vertical', padding=10, spacing=8)

        # 1. 헤더 영역
        title = Label(text="🧾 영수증 더치페이 정산기", font_size='18sp', bold=True, size_hint_y=None, height=35)
        main_layout.add_widget(title)

        # 2. 이미지 업로드 & 샘플 로드 버튼
        btn_top_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=40, spacing=5)
        
        file_btn = Button(text="📷 영수증 선택", background_color=(0.3, 0.7, 0.4, 1))
        file_btn.bind(on_press=self.open_file_chooser)
        
        sample_btn = Button(text="🧪 샘플 로드")
        sample_btn.bind(on_press=self.load_sample_data)
        
        btn_top_box.add_widget(file_btn)
        btn_top_box.add_widget(sample_btn)
        main_layout.add_widget(btn_top_box)

        # 3. 참여자 입력 영역
        member_box = BoxLayout(orientation='horizontal', size_hint_y=None, height=40, spacing=5)
        member_box.add_widget(Label(text="참여자:", size_hint_x=0.25))
        self.member_input_field = TextInput(text="철수, 영희, 민수", multiline=False, size_hint_x=0.75)
        member_box.add_widget(self.member_input_field)
        main_layout.add_widget(member_box)

        # 4. 동적 스크롤 영역 (인식된 메뉴 및 먹은 수량 선택)
        self.scroll = ScrollView(size_hint=(1, 1))
        self.content_layout = BoxLayout(orientation='vertical', size_hint_y=None, spacing=10)
        self.content_layout.bind(minimum_height=self.content_layout.setter('height'))
        self.scroll.add_widget(self.content_layout)
        main_layout.add_widget(self.scroll)

        # 5. 하단 정산 실행 버튼
        calc_btn = Button(text="⚡ 정산하기", size_hint_y=None, height=50, background_color=(0.2, 0.6, 1, 1), bold=True)
        calc_btn.bind(on_press=self.calculate_settlement)
        main_layout.add_widget(calc_btn)

        return main_layout

    # ----------------------------------------------------
    # 데이터 로드 및 UI 동적 업데이트
    # ----------------------------------------------------
    def load_sample_data(self, instance):
        """샘플 데이터 로드"""
        self.items = [
            {"item": "삼겹살", "price": 20000, "qty": 2},
            {"item": "된장찌개", "price": 7000, "qty": 1},
            {"item": "소주", "price": 10000, "qty": 2},
        ]
        self.receipt_total = 37000
        self.render_items_ui()

    def open_file_chooser(self, instance):
        """파일 선택 팝업창"""
        content = BoxLayout(orientation='vertical')
        file_chooser = FileChooserIconView(path=".")
        btn_box = BoxLayout(size_hint_y=None, height=40)
        
        select_btn = Button(text="선택")
        cancel_btn = Button(text="취소")
        btn_box.add_widget(select_btn)
        btn_box.add_widget(cancel_btn)
        
        content.add_widget(file_chooser)
        content.add_widget(btn_box)

        popup = Popup(title="영수증 이미지 선택", content=content, size_hint=(0.9, 0.9))

        def on_select(btn_obj):
            if file_chooser.selection:
                file_path = file_chooser.selection[0]
                with open(file_path, "rb") as f:
                    img_bytes = f.read()
                self.items, self.receipt_total = parse_receipt_items_and_total(img_bytes)
                if not self.items:
                    self.load_sample_data(None)
                else:
                    self.render_items_ui()
            popup.dismiss()

        select_btn.bind(on_press=on_select)
        cancel_btn.bind(on_press=popup.dismiss)
        popup.open()

    def render_items_ui(self):
        """인식된 메뉴별 참여자 선택 UI 동적 생성"""
        self.content_layout.clear_widgets()
        self.member_inputs.clear()

        # 참여자 파싱
        self.members = [m.strip() for m in self.member_input_field.text.split(",") if m.strip()]
        if not self.members:
            self.members = ["철수", "영희", "민수"]

        # 총액 표시
        total_label = Label(
            text=f"📋 인식 총액: {self.receipt_total:,}원", 
            size_hint_y=None, height=30, bold=True, color=(1, 0.8, 0.2, 1)
        )
        self.content_layout.add_widget(total_label)

        # 메뉴 카드별 UI 생성
        for idx, item in enumerate(self.items):
            card = BoxLayout(orientation='vertical', size_hint_y=None, padding=8, spacing=5)
            card.height = 40 + (len(self.members) * 35)

            # 메뉴 기본 정보 Header
            header_text = f"🍽️ {item['item']} ({item['price']:,}원 / 총 {item['qty']}개)"
            card.add_widget(Label(text=header_text, size_hint_y=None, height=25, bold=True, halign='left'))

            # 멤버별 체크박스 및 수량 입력 줄
            for member in self.members:
                row = BoxLayout(orientation='horizontal', size_hint_y=None, height=30, spacing=5)
                
                chk = CheckBox(size_hint_x=0.15, active=True)
                m_label = Label(text=member, size_hint_x=0.4, halign='left')
                qty_input = TextInput(text="1", multiline=False, input_filter='int', size_hint_x=0.45)

                row.add_widget(chk)
                row.add_widget(m_label)
                row.add_widget(qty_input)
                card.add_widget(row)

                self.member_inputs[(idx, member)] = {"chk": chk, "qty": qty_input}

            self.content_layout.add_widget(card)

    # ----------------------------------------------------
    # 4. 정산 결과 계산 및 팝업
    # ----------------------------------------------------
    def calculate_settlement(self, instance):
        if not self.items:
            return

        self.members = [m.strip() for m in self.member_input_field.text.split(",") if m.strip()]
        member_totals = {m: 0.0 for m in self.members}

        # 메뉴별 지분 계산
        for idx, entry in enumerate(self.items):
            price = entry["price"]
            item_shares = {}

            for member in self.members:
                key = (idx, member)
                if key in self.member_inputs:
                    chk_val = self.member_inputs[key]["chk"].active
                    qty_val = self.member_inputs[key]["qty"].text
                    
                    if chk_val and qty_val.isdigit() and int(qty_val) > 0:
                        item_shares[member] = int(qty_val)

            total_selected_qty = sum(item_shares.values())
            if total_selected_qty > 0:
                for member, share in item_shares.items():
                    member_totals[member] += (price * (share / total_selected_qty))

        # 메시지 구성
        msg = "[더치페이 정산 요청]\n\n"
        calculated_total = 0
        for member, total_price in member_totals.items():
            final_amount = round(total_price)
            calculated_total += final_amount
            msg += f"• {member}: {final_amount:,}원\n"
            
        msg += f"\n인식 총액: {self.receipt_total:,}원"
        msg += f"\n계산 총액: {calculated_total:,}원"

        # 결과 팝업 표시
        popup_content = BoxLayout(orientation='vertical', padding=10, spacing=10)
        res_label = Label(text=msg, halign='left', valign='top')
        close_btn = Button(text="확인", size_hint_y=None, height=40)

        popup_content.add_widget(res_label)
        popup_content.add_widget(close_btn)

        popup = Popup(title="최종 정산 결과", content=popup_content, size_hint=(0.85, 0.65))
        close_btn.bind(on_press=popup.dismiss)
        popup.open()


if __name__ == '__main__':
    ReceiptApp().run()