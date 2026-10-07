import os
import re
import datetime
import json
import tempfile
import time
import threading
import urllib.parse
import urllib.request
import urllib.error
import mimetypes
import ssl
import certifi
import uuid
HTTPS_CONTEXT = ssl.create_default_context(cafile=certifi.where())
from fractions import Fraction
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
from kivy.core.window import Window
from kivy.core.text import LabelBase
from kivy.graphics import Color, RoundedRectangle
from kivy.metrics import dp
from kivy.properties import NumericProperty
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.checkbox import CheckBox
from kivy.uix.filechooser import FileChooserListView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.screenmanager import ScreenManager, Screen
from kivy.uix.scrollview import ScrollView
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.textinput import TextInput
from kivy.uix.widget import Widget

try:
    from plyer import camera as plyer_camera
except Exception:
    plyer_camera = None

try:
    from plyer import notification as plyer_notification
except Exception:
    plyer_notification = None

try:
    from kivy.utils import platform
except Exception:
    platform = "unknown"



# ============================================================
# CONFIG
# ============================================================
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
# 실제 배포 서버 주소로 환경변수 API_BASE_URL을 지정하세요.
API_BASE_URL = os.getenv("API_BASE_URL", "https://dcw-6vyo.onrender.com").rstrip("/")
WEB_URL = os.getenv("WEB_URL", "https://bawibagae.github.io/DCW-web/")

LOCAL_REGULAR_FONT = os.path.join(BASE_DIR, "NanumGothic.ttf")
LOCAL_BOLD_FONT = os.path.join(BASE_DIR, "NanumGothicBold.ttf")

FONT_REGULAR = "Roboto"
FONT_BOLD = "Roboto"

if os.path.isfile(LOCAL_REGULAR_FONT):
    try:
        LabelBase.register(name="AppKoreanRegular", fn_regular=LOCAL_REGULAR_FONT)
        FONT_REGULAR = "AppKoreanRegular"
    except Exception:
        pass

if os.path.isfile(LOCAL_BOLD_FONT):
    try:
        LabelBase.register(name="AppKoreanBold", fn_regular=LOCAL_BOLD_FONT)
        FONT_BOLD = "AppKoreanBold"
    except Exception:
        if FONT_REGULAR != "Roboto":
            FONT_BOLD = FONT_REGULAR

if FONT_REGULAR == "Roboto":
    candidates = (
        ["/system/fonts/NotoSansCJK-Regular.ttc",
         "/system/fonts/NotoSansCJKkr-Regular.otf",
         "/system/fonts/NotoSansKR-Regular.otf",
         "/system/fonts/NanumGothic.ttf"]
        if platform == "android"
        else [r"C:\Windows\Fonts\malgun.ttf", r"C:\Windows\Fonts\NanumGothic.ttf"]
    )
    for path in candidates:
        if os.path.isfile(path):
            try:
                LabelBase.register(name="AppKoreanRegular", fn_regular=path)
                FONT_REGULAR = "AppKoreanRegular"
                FONT_BOLD = FONT_REGULAR
                break
            except Exception:
                pass


# ============================================================
# OCR
# ============================================================
# OCR is handled by the Render server.


# ============================================================
# SESSION
# ============================================================
SESSION_STATE = {
    "token": None,
    "current_user": None,
    "history": [],
    "receipts": [],
    "friends": [],
    "notifications": [],
}


def api_request(method, path, json_data=None, auth=True, timeout=70, token=None):
    headers = {"Content-Type": "application/json"}
    if auth and token:
        headers["Authorization"] = f"Bearer {token}"
    url = f"{API_BASE_URL}{path}"
    body = None if json_data is None else json.dumps(json_data).encode("utf-8")
    req = urllib.request.Request(url=url, data=body, headers=headers, method=method.upper())
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=HTTPS_CONTEXT) as response:
            status_code = response.status
            raw = response.read()
    except urllib.error.HTTPError as exc:
        status_code = exc.code
        raw = exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"서버 연결 실패\n{url}\n{exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError(f"서버 응답 오류 (HTTP {status_code})\n요청: {path}\n서버 배포 로그를 확인해 주세요. 서버가 재시작 중일 수도 있습니다.") from exc
    if status_code >= 400:
        message = data.get("error", "서버 오류") if isinstance(data, dict) else "서버 오류"
        trace = data.get("request_id") if isinstance(data, dict) else None
        suffix = f"\n요청 ID: {trace}" if trace and str(trace) not in str(message) else ""
        raise RuntimeError(f"HTTP {status_code} · {path}\n{message}{suffix}")
    return data


def _multipart_upload_image(path, token, timeout=75):
    if os.path.getsize(path) > 10 * 1024 * 1024:
        raise ValueError("이미지는 10MB 이하로 선택해 주세요.")
    with open(path, "rb") as image_file:
        image_bytes = image_file.read()
    boundary = "----DutchPayBoundary" + format(int(time.time() * 1000000), "x")
    mime_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
    filename = os.path.basename(path) or "receipt.jpg"
    body = b"".join([
        f"--{boundary}\r\n".encode("utf-8"),
        f'Content-Disposition: form-data; name="image"; filename="{filename}"\r\n'.encode("utf-8"),
        f"Content-Type: {mime_type}\r\n\r\n".encode("utf-8"),
        image_bytes,
        b"\r\n",
        f"--{boundary}--\r\n".encode("utf-8"),
    ])
    req = urllib.request.Request(
        url=f"{API_BASE_URL}/api/ocr",
        data=body,
        method="POST",
        headers={"Authorization": f"Bearer {token}", "Content-Type": f"multipart/form-data; boundary={boundary}"},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=HTTPS_CONTEXT) as response:
            status_code, raw = response.status, response.read()
    except urllib.error.HTTPError as exc:
        status_code, raw = exc.code, exc.read()
    except (urllib.error.URLError, TimeoutError) as exc:
        raise RuntimeError(f"OCR 서버 연결 실패\n{exc}") from exc
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception as exc:
        raise RuntimeError("OCR 서버가 JSON 대신 다른 응답을 반환했습니다.") from exc
    if status_code >= 400:
        raise RuntimeError(data.get("error", f"OCR 서버 오류 ({status_code})"))
    return data

def async_api(method, path, json_data, on_success, on_error, auth=True):
    token = SESSION_STATE.get("token") if auth else None
    def worker():
        try:
            result = api_request(method, path, json_data, auth=auth, token=token)
            Clock.schedule_once(lambda _dt, value=result: on_success(value), 0)
        except Exception as e:
            Clock.schedule_once(lambda _dt, message=str(e): on_error(message), 0)

    threading.Thread(target=worker, daemon=True).start()


# ============================================================
# INDEX.HTML 기반 색상/컴포넌트
# ============================================================
COLOR_BG = (0.956, 0.965, 0.973, 1)          # #f4f6f8
COLOR_SURFACE = (1, 1, 1, 1)
COLOR_SURFACE_BLUE = (0.933, 0.949, 1, 1)    # #eef2ff
COLOR_PRIMARY = (0.231, 0.510, 0.965, 1)     # #3b82f6
COLOR_PRIMARY_DARK = (0.118, 0.106, 0.294, 1)
COLOR_PRIMARY_LIGHT = (0.878, 0.906, 0.996, 1)
COLOR_TEXT = (0.102, 0.114, 0.125, 1)
COLOR_MUTED = (0.39, 0.42, 0.45, 1)
COLOR_BORDER = (0.86, 0.89, 0.93, 1)
COLOR_SUCCESS = (0.12, 0.56, 0.31, 1)


def make_label(text="", font_size=16, bold=False, **kwargs):
    color = kwargs.pop("color", COLOR_TEXT)
    return Label(
        text=text,
        font_name=FONT_BOLD if bold else FONT_REGULAR,
        font_size=dp(font_size),
        color=color,
        **kwargs,
    )


class SoftButton(Button):
    def __init__(self, tone, **kwargs):
        super().__init__(background_normal="", background_down="", background_color=(0,0,0,0), **kwargs)
        with self.canvas.before:
            self._tone = Color(*tone)
            self._shape = RoundedRectangle(radius=[dp(12)])
        self.bind(pos=self._draw, size=self._draw, state=self._draw, disabled=self._draw)
        self._draw()
    def _draw(self,*_):
        self._shape.pos=self.pos
        self._shape.size=self.size
        self._tone.a=0.45 if self.disabled else (0.8 if self.state=="down" else 1)


def make_button(text="",bold=False,**kwargs):
    return SoftButton(COLOR_PRIMARY_LIGHT,text=text,font_name=FONT_BOLD if bold else FONT_REGULAR,
                      font_size=dp(14),color=COLOR_TEXT,**kwargs)


def make_primary_button(text="",**kwargs):
    return SoftButton(COLOR_PRIMARY,text=text,font_name=FONT_BOLD,font_size=dp(15),color=(1,1,1,1),**kwargs)


def make_text_input(**kwargs):
    return TextInput(
        font_name=FONT_REGULAR,
        foreground_color=COLOR_TEXT,
        background_color=COLOR_SURFACE,
        cursor_color=COLOR_PRIMARY,
        hint_text_color=COLOR_MUTED,
        padding=[dp(12), dp(10), dp(12), dp(10)],
        **kwargs,
    )


class BaseLayout(BoxLayout):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        with self.canvas.before:
            Color(*COLOR_BG)
            self._bg = RoundedRectangle(radius=[0])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size


class Card(BoxLayout):
    def __init__(self, **kwargs):
        orientation = kwargs.pop("orientation", "vertical")
        super().__init__(orientation=orientation, padding=dp(14), spacing=dp(6), **kwargs)
        with self.canvas.before:
            Color(*COLOR_SURFACE)
            self._bg = RoundedRectangle(radius=[dp(14)])
        self.bind(pos=self._update_bg, size=self._update_bg)

    def _update_bg(self, *_):
        self._bg.pos = self.pos
        self._bg.size = self.size


class KoreanSpinnerOption(SpinnerOption):
    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT_REGULAR)
        kwargs.setdefault("font_size", dp(15))
        kwargs.setdefault("color", COLOR_TEXT)
        kwargs.setdefault("background_normal", "")
        kwargs.setdefault("background_color", COLOR_SURFACE)
        super().__init__(**kwargs)


def show_message(title, message):
    content = BoxLayout(orientation="vertical", padding=dp(16), spacing=dp(12))
    scroll = ScrollView(do_scroll_x=False)
    label = make_label(str(message), 14, color=(1,1,1,1), halign="left", valign="top", size_hint_y=None)
    label.bind(width=lambda obj,w: setattr(obj,"text_size",(max(dp(40),w),None)))
    label.bind(texture_size=lambda obj,v: setattr(obj,"height",v[1]+dp(16)))
    scroll.add_widget(label)
    content.add_widget(scroll)
    btn=make_primary_button("확인",size_hint_y=None,height=dp(48))
    content.add_widget(btn)
    popup=Popup(title=title,title_font=FONT_BOLD,content=content,size_hint=(0.92,0.55),auto_dismiss=False)
    btn.bind(on_release=lambda *_: popup.dismiss())
    popup.open()
    return popup


def show_toast(message):
    content = make_label(message, 14, True, halign="center", valign="middle")
    popup = Popup(
        content=content,
        size_hint=(None, None),
        size=(dp(280), dp(56)),
        separator_height=0,
        background="",
        auto_dismiss=True,
    )
    popup.open()
    Clock.schedule_once(lambda *_: popup.dismiss(), 1.6)


def add_logo_header(screen):
    header = BoxLayout(orientation="horizontal", size_hint_y=None,
                       height=dp(62), spacing=dp(8))
    logo = SoftButton(COLOR_PRIMARY_DARK, text="DUTCH\n더치페이",
                      font_name=FONT_BOLD, font_size=dp(17),
                      color=(1, 1, 1, 1), size_hint_x=None, width=dp(112))
    def home(*_):
        if screen.manager:
            screen.manager.transition.direction = "right"
            screen.manager.current = "home"
    logo.bind(on_release=home)
    header.add_widget(logo)
    header.add_widget(Widget())
    if screen.name != "home":
        button = make_button("홈", size_hint_x=None, width=dp(44))
        button.bind(on_release=home)
        header.add_widget(button)
    user = make_button("로그인", bold=True, size_hint_x=None, width=dp(88))
    def refresh(*_):
        user.text = "마이페이지" if SESSION_STATE["current_user"] else "로그인"
    refresh()
    screen.bind(on_pre_enter=refresh)
    user.bind(on_release=lambda *_: setattr(screen.manager, "current",
              "mypage" if SESSION_STATE["current_user"] else "login"))
    header.add_widget(user)
    return header


def add_page_layout():
    return BaseLayout(orientation="vertical", padding=dp(14), spacing=dp(11))


# ============================================================
# OCR
# ============================================================
def parse_receipt_items_and_total(image_bytes):
    if vision is None:
        return [], 0
    try:
        client = vision.ImageAnnotatorClient()
        image = vision.Image(content=image_bytes)
        response = client.text_detection(image=image)
        texts = response.text_annotations
        if not texts:
            return [], 0

        lines = texts[0].description.split("\n")
        items = []
        detected_total = 0

        ignore_keywords = [
            "등록", "POS", "pos", "포스", "일시", "날짜", "시간", "점포",
            "가맹점", "사업자", "대표", "TEL", "Tel", "tel", "주소",
            "승인", "카드", "현금", "VAT", "vat", "부가세", "TAX", "tax",
            "테이블", "주문", "영수증", "BILL", "Bill", "전표", "고객",
        ]
        total_keywords = ["합계", "총액", "총결제금액", "결제금액", "받을금액", "TOTAL", "Total"]

        for line in lines:
            line_str = line.strip()
            if not line_str:
                continue

            if any(keyword in line_str for keyword in total_keywords):
                numbers = re.findall(r"[\d,]+", line_str)
                if numbers:
                    value = int(numbers[-1].replace(",", ""))
                    detected_total = max(detected_total, value)
                continue

            if any(k in line_str for k in ignore_keywords):
                continue

            match_three = re.search(r"^(.+?)\s+(\d+)\s+([\d,]+)원?$", line_str)
            match_two = re.search(r"^(.+?)\s+([\d,]+)원?$", line_str)

            if match_three:
                item_name = match_three.group(1).strip()
                qty = int(match_three.group(2))
                price_str = match_three.group(3).replace(",", "")
                if price_str.isdigit():
                    price = int(price_str)
                    if 500 <= price <= 1_000_000:
                        items.append({"item": item_name, "price": price, "qty": qty})

            elif match_two:
                item_name = match_two.group(1).strip()
                price_str = match_two.group(2).replace(",", "")
                cleaned = re.sub(r"[\[\]\(\)\{\}\:\-\=\.\,]", "", item_name).strip()
                if cleaned.isdigit() or not cleaned:
                    continue
                if price_str.isdigit():
                    price = int(price_str)
                    if 500 <= price <= 1_000_000:
                        qty_match = re.search(r"(\d+)\s*(인분|개|병|잔|개입|줄)?", item_name)
                        qty = int(qty_match.group(1)) if qty_match else 1
                        items.append({"item": item_name, "price": price, "qty": qty})

        if detected_total == 0 and items:
            detected_total = sum(item["price"] for item in items)
        return items, detected_total

    except Exception as e:
        print(f"OCR 분석 중 오류가 발생했습니다: {e}")
        return [], 0


# ============================================================
# HOME
# ============================================================
class HomeScreen(Screen):
    def on_enter(self):
        self.clear_widgets()
        main = add_page_layout()
        main.add_widget(add_logo_header(self))

        title_row = BoxLayout(size_hint_y=None, height=dp(42))
        title_row.add_widget(make_label("정산 내역", 21, True))
        refresh = make_button("새로고침", size_hint_x=None, width=dp(82))
        refresh.bind(on_press=lambda *_: self.refresh())
        title_row.add_widget(refresh)
        main.add_widget(title_row)

        if SESSION_STATE["current_user"]:
            info = make_label(
                f"{SESSION_STATE['current_user']['name']}님 환영합니다.",
                14, False, color=COLOR_MUTED, size_hint_y=None, height=dp(26)
            )
            main.add_widget(info)

        scroll = ScrollView()
        history_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(10))
        history_box.bind(minimum_height=history_box.setter("height"))

        history = SESSION_STATE["history"]
        if not history:
            history_box.add_widget(make_label(
                "아직 더치페이 내역이 없습니다.",
                size_hint_y=None, height=dp(50), halign="center"
            ))
        else:
            for item in reversed(history):
                card = Card(size_hint_y=None, height=dp(98))
                card.add_widget(make_label(
                    f"{item['date']} · {item['count']}개 영수증", 17, True,
                    size_hint_y=None, height=dp(25)
                ))
                card.add_widget(make_label(
                    f"총액: {item['total']:,}원 ({len(item['members'])}명)",
                    size_hint_y=None, height=dp(25)
                ))
                card.add_widget(make_label(
                    f"참여자: {', '.join(item['members'])}",
                    13, False, color=COLOR_MUTED,
                    size_hint_y=None, height=dp(25)
                ))
                history_box.add_widget(card)

        scroll.add_widget(history_box)
        main.add_widget(scroll)

        action_row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        scan = make_primary_button("영수증 스캔", size_hint_x=0.72)
        scan.bind(on_press=self.start_new_settlement)
        friends = make_button("친구", size_hint_x=0.28)
        friends.bind(on_press=lambda *_: setattr(self.manager, "current", "friends"))
        action_row.add_widget(scan)
        action_row.add_widget(friends)
        main.add_widget(action_row)

        notice = make_button("알림 확인", size_hint_y=None, height=dp(45))
        notice.bind(on_press=lambda *_: setattr(self.manager, "current", "notifications"))
        main.add_widget(notice)

        self.add_widget(main)

    def refresh(self):
        if SESSION_STATE["current_user"]:
            load_history_from_server()
            load_notifications_from_server()
        self.on_enter()

    def start_new_settlement(self, *_):
        SESSION_STATE["receipts"] = []
        self.manager.current = "camera"


# ============================================================
# LOGIN / SIGNUP
# ============================================================
def auth_submit(screen, button, path, payload, success):
    if getattr(screen,"_auth_busy",False):
        return
    screen._auth_busy=True
    caption=button.text
    button.disabled=True
    button.text="처리 중..."
    status=make_label("서버에 연결하고 있습니다.",13,color=COLOR_MUTED,size_hint_y=None,height=dp(38))
    button.parent.add_widget(status,index=0)
    def waiting(_dt):
        status.text="서버 시작을 기다리는 중입니다. 잠시만 기다려 주세요."
    timer=Clock.schedule_once(waiting,8)
    def finish():
        screen._auth_busy=False
        timer.cancel()
        button.disabled=False
        button.text=caption
        if status.parent: status.parent.remove_widget(status)
    def ok(data):
        finish()
        success(data)
    def fail(message):
        finish()
        show_message("요청 실패",message)
    async_api("POST",path,payload,ok,fail,auth=False)


class LoginScreen(Screen):
    def on_enter(self):
        async_api("GET","/api/health",None,lambda data:None,lambda err:None,auth=False)

    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.build_ui()

    def build_ui(self):
        main = add_page_layout()
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("로그인", 22, True, size_hint_y=None, height=dp(44)))

        self.email_input = make_text_input(
            hint_text="이메일",
            multiline=False,
            size_hint_y=None,
            height=dp(46),
        )
        self.pw_input = make_text_input(
            hint_text="비밀번호",
            password=True,
            multiline=False,
            size_hint_y=None,
            height=dp(46),
        )
        login_clip = BoxLayout(size_hint_y=None, height=dp(42), spacing=dp(7))
        email_paste = make_button("이메일 붙여넣기", size_hint_x=0.5)
        email_paste.bind(on_press=lambda *_: self._paste_login(self.email_input))
        pw_paste = make_button("비밀번호 붙여넣기", size_hint_x=0.5)
        pw_paste.bind(on_press=lambda *_: self._paste_login(self.pw_input))
        login_clip.add_widget(email_paste)
        login_clip.add_widget(pw_paste)

        main.add_widget(self.email_input)
        main.add_widget(self.pw_input)
        main.add_widget(login_clip)

        login = make_primary_button(
            "로그인",
            size_hint=(None, None),
            width=dp(150),
            height=dp(42),
            pos_hint={"center_x": 0.5},
        )
        login.bind(on_press=self.do_login)
        main.add_widget(login)

        signup = make_button("회원가입 하러가기", size_hint_y=None, height=dp(42))
        signup.bind(on_press=lambda *_: setattr(self.manager, "current", "signup"))
        main.add_widget(signup)
        main.add_widget(Widget())
        self.add_widget(main)

    def _paste_login(self, target):
        try:
            text = Clipboard.paste() or ""
        except Exception as e:
            show_message("붙여넣기 실패", str(e))
            return
        target.text = text.strip()

    def do_login(self, *_):
        email = self.email_input.text.strip()
        pw = self.pw_input.text.strip()
        if not email or not pw:
            show_message("경고", "이메일과 비밀번호를 입력해 주세요.")
            return

        auth_submit(self, _[0], "/api/auth/login",
                    {"email":email,"password":pw},self.login_success)

    def login_success(self, data):
        SESSION_STATE["token"] = data["token"]
        SESSION_STATE["current_user"] = data["user"]
        self.email_input.text = ""
        self.pw_input.text = ""
        load_friends_from_server()
        load_notifications_from_server()
        load_history_from_server()
        App.get_running_app().start_notification_polling()
        self.manager.current = "home"


class SignupScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.build_ui()

    def build_ui(self):
        main = add_page_layout()
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("회원가입", 22, True, size_hint_y=None, height=dp(44)))

        self.name_input = make_text_input(hint_text="이름", multiline=False, size_hint_y=None, height=dp(46))
        self.email_input = make_text_input(hint_text="이메일", multiline=False, size_hint_y=None, height=dp(46))
        self.pw_input = make_text_input(hint_text="비밀번호 (6자 이상)", password=True, multiline=False,
                                        size_hint_y=None, height=dp(46))
        main.add_widget(self.name_input)
        main.add_widget(self.email_input)
        main.add_widget(self.pw_input)

        submit = make_primary_button(
            "가입완료",
            size_hint=(None, None),
            width=dp(150),
            height=dp(42),
            pos_hint={"center_x": 0.5},
        )
        submit.bind(on_press=self.do_signup)
        main.add_widget(submit)

        cancel = make_button("취소", size_hint_y=None, height=dp(42))
        cancel.bind(on_press=lambda *_: setattr(self.manager, "current", "login"))
        main.add_widget(cancel)
        main.add_widget(Widget())
        self.add_widget(main)

    def do_signup(self, *_):
        name = self.name_input.text.strip()
        email = self.email_input.text.strip()
        pw = self.pw_input.text.strip()
        if not name or not email or not pw:
            show_message("경고", "모든 항목을 입력해 주세요.")
            return

        if len(pw)<6:
            show_message("비밀번호 확인","비밀번호는 6자 이상 입력해 주세요.")
            return
        auth_submit(self, _[0], "/api/auth/register",
                    {"name":name,"email":email,"password":pw},lambda data:self.signup_success())

    def signup_success(self):
        self.name_input.text = ""
        self.email_input.text = ""
        self.pw_input.text = ""
        show_toast("회원가입이 완료되었습니다.")
        self.manager.current = "login"


# ============================================================
# FRIENDS
# ============================================================
class FriendsScreen(Screen):
    def on_enter(self):
        self.build_ui()
        if SESSION_STATE["current_user"]:
            load_friends_from_server()

    def build_ui(self):
        self.clear_widgets()
        main = add_page_layout()
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("친구", 22, True, size_hint_y=None, height=dp(44)))

        add_row = BoxLayout(size_hint_y=None, height=dp(46), spacing=dp(8))
        self.friend_input = make_text_input(hint_text="친구 이메일 또는 이름", multiline=False)
        add_btn = make_primary_button("친구 추가", size_hint_x=None, width=dp(95))
        add_btn.bind(on_press=self.add_friend)
        add_row.add_widget(self.friend_input)
        add_row.add_widget(add_btn)
        main.add_widget(add_row)

        self.status = make_label("", 13, color=COLOR_MUTED, size_hint_y=None, height=dp(24))
        main.add_widget(self.status)

        scroll = ScrollView()
        self.friend_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.friend_box.bind(minimum_height=self.friend_box.setter("height"))
        scroll.add_widget(self.friend_box)
        main.add_widget(scroll)

        back = make_button("뒤로", size_hint_y=None, height=dp(44))
        back.bind(on_press=lambda *_: setattr(self.manager, "current", "home"))
        main.add_widget(back)
        self.add_widget(main)
        self.render_friends()

    def render_friends(self):
        self.friend_box.clear_widgets()
        friends = SESSION_STATE.get("friends", [])
        if not friends:
            self.friend_box.add_widget(make_label(
                "아직 친구가 없습니다.",
                size_hint_y=None, height=dp(50), halign="center"
            ))
            return
        for friend in friends:
            card = Card(orientation="horizontal", size_hint_y=None, height=dp(64))
            card.add_widget(make_label(friend["name"], 16, True, size_hint_x=0.45))
            card.add_widget(make_label(friend["email"], 13, color=COLOR_MUTED, size_hint_x=0.55,
                                       halign="right", valign="middle"))
            self.friend_box.add_widget(card)

    def add_friend(self, *_):
        value = self.friend_input.text.strip()
        if not value:
            show_message("경고", "친구의 이메일 또는 이름을 입력해 주세요.")
            return

        async_api(
            "POST", "/api/friends/add",
            {"email_or_name": value},
            lambda data: self.friend_added(data),
            lambda err: show_message("친구 추가 실패", err),
        )

    def friend_added(self, data):
        self.friend_input.text = ""
        self.status.text = f"{data['name']}님을 친구로 추가했습니다."
        load_friends_from_server()
        show_toast("친구 추가 완료")


# ============================================================
# MY PAGE
# ============================================================
class MyPageScreen(Screen):
    def on_enter(self):
        self.clear_widgets()
        main = add_page_layout()
        main.add_widget(add_logo_header(self))

        user = SESSION_STATE["current_user"]
        if not user:
            self.manager.current = "login"
            return

        main.add_widget(make_label("마이페이지", 22, True, size_hint_y=None, height=dp(44)))

        card = Card(size_hint_y=None, height=dp(100))
        card.add_widget(make_label(f"이름: {user['name']}", 17, True, size_hint_y=None, height=dp(34)))
        card.add_widget(make_label(f"이메일: {user['email']}", color=COLOR_MUTED, size_hint_y=None, height=dp(28)))
        main.add_widget(card)

        friends = make_button("친구 관리", size_hint_y=None, height=dp(46))
        friends.bind(on_press=lambda *_: setattr(self.manager, "current", "friends"))
        main.add_widget(friends)

        notifications = make_button("알림 보기", size_hint_y=None, height=dp(46))
        notifications.bind(on_press=lambda *_: setattr(self.manager, "current", "notifications"))
        main.add_widget(notifications)

        logout = make_button("로그아웃", size_hint_y=None, height=dp(46))
        logout.bind(on_press=self.do_logout)
        main.add_widget(logout)
        main.add_widget(Widget())
        self.add_widget(main)

    def do_logout(self, *_):
        token = SESSION_STATE.get("token")
        if token:
            async_api("POST", "/api/auth/logout", {}, lambda _data: None, lambda _err: None)
        SESSION_STATE["token"] = None
        SESSION_STATE["current_user"] = None
        SESSION_STATE["friends"] = []
        SESSION_STATE["notifications"] = []
        self.manager.current = "home"


# ============================================================
# NOTIFICATIONS
# ============================================================
class NotificationsScreen(Screen):
    def on_enter(self):
        self.clear_widgets()
        main = add_page_layout()
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("알림", 22, True, size_hint_y=None, height=dp(44)))

        scroll = ScrollView()
        self.box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.box.bind(minimum_height=self.box.setter("height"))
        scroll.add_widget(self.box)
        main.add_widget(scroll)

        back = make_button("뒤로", size_hint_y=None, height=dp(44))
        back.bind(on_press=lambda *_: setattr(self.manager, "current", "home"))
        main.add_widget(back)
        self.add_widget(main)
        self.render()

        if SESSION_STATE["current_user"]:
            load_notifications_from_server()

    def render(self):
        self.box.clear_widgets()
        notifications = SESSION_STATE.get("notifications", [])
        if not notifications:
            self.box.add_widget(make_label("새 알림이 없습니다.", size_hint_y=None, height=dp(50), halign="center"))
            return

        for n in notifications:
            title = f"● {n['title']}" if not n.get("read") else n["title"]
            card = Card(size_hint_y=None, height=dp(88))
            card.add_widget(make_label(title, 16, True, size_hint_y=None, height=dp(28)))
            card.add_widget(make_label(n["message"], 13, color=COLOR_MUTED, size_hint_y=None, height=dp(30)))
            card.add_widget(make_label(n["created_at"][:16].replace("T", " "),
                                       11, color=COLOR_MUTED, size_hint_y=None, height=dp(20)))
            self.box.add_widget(card)


# ============================================================
# CAMERA
# ============================================================
class PhoneCamera(BoxLayout):
    def __init__(self, on_capture, on_close, **kwargs):
        super().__init__(orientation="vertical", spacing=dp(10), padding=dp(12), **kwargs)
        self.on_capture = on_capture
        self.on_close = on_close
        self.closed = False
        self.camera_path = None

        self.info = make_label(
            "휴대폰 카메라로 영수증을 촬영합니다.",
            15, halign="center", valign="middle", size_hint_y=None, height=dp(70)
        )
        self.add_widget(self.info)

        open_button = make_primary_button("📷 휴대폰 카메라 열기", size_hint_y=None, height=dp(56))
        open_button.bind(on_press=self.open_camera)
        self.add_widget(open_button)

        close_button = make_button("닫기", size_hint_y=None, height=dp(50))
        close_button.bind(on_press=self.close)
        self.add_widget(close_button)
        self.add_widget(Widget())

        if platform != "android":
            self.info.text = "PC에서는 테스트 모드입니다.\nAndroid APK에서는 휴대폰 기본 카메라가 실행됩니다."

    def open_camera(self, *_):
        if platform == "android":
            try:
                from android.permissions import request_permissions, Permission

                def permission_callback(_permissions, grants):
                    if all(grants):
                        Clock.schedule_once(lambda *_: self.take_picture_android(), 0)
                    else:
                        Clock.schedule_once(
                            lambda *_: show_message("카메라 권한", "영수증 촬영을 위해 카메라 권한을 허용해 주세요."),
                            0,
                        )

                request_permissions([Permission.CAMERA], permission_callback)
                return
            except Exception as e:
                show_message("카메라 권한 오류", f"카메라 권한을 요청하지 못했습니다.\n{e}")
                return

        self.take_picture_pc()

    def take_picture_android(self):
        from android.runnable import run_on_ui_thread
        run_on_ui_thread(self._launch_camera_android)()

    def _launch_camera_android(self):
        """Open the native Android camera using FileProvider.

        Plyer's camera provider can pass a file:// URI to Android on some
        devices, which raises FileUriExposedException on Android 7+.
        We create a content:// URI ourselves through FileProvider instead.
        """
        try:
            from jnius import autoclass

            PythonActivity = autoclass("org.kivy.android.PythonActivity")
            Intent = autoclass("android.content.Intent")
            MediaStore = autoclass("android.provider.MediaStore")
            File = autoclass("java.io.File")


            activity = PythonActivity.mActivity
            context = activity.getApplicationContext()

            filename = os.path.join(
                str(context.getCacheDir().getAbsolutePath()),
                f"dutchpay_receipt_{time.time_ns()}.jpg",
            )
            os.makedirs(os.path.dirname(filename),exist_ok=True)
            self.camera_path = filename

            # FileProvider is registered in AndroidManifest.xml.
            authority = context.getPackageName() + ".fileprovider"
            file_obj = File(filename)
            self._camera_media_uri = None
            try:
                FileProvider = autoclass("androidx.core.content.FileProvider")
                uri = FileProvider.getUriForFile(context, authority, file_obj)
            except Exception:
                # Android 10+: app-owned MediaStore content URI needs no
                # FileProvider declaration or broad storage permission.
                BuildVersion = autoclass("android.os.Build$VERSION")
                if BuildVersion.SDK_INT < 29:
                    raise RuntimeError("Android 9 이하에서는 FileProvider XML과 buildozer 설정을 적용하고 APK를 재빌드해야 합니다.")
                ContentValues = autoclass("android.content.ContentValues")
                values = ContentValues()
                values.put("_display_name", os.path.basename(filename))
                values.put("mime_type", "image/jpeg")
                values.put("relative_path", "Pictures/DutchPay")
                uri = context.getContentResolver().insert(
                    MediaStore.Images.Media.EXTERNAL_CONTENT_URI, values)
                if uri is None:
                    raise RuntimeError("카메라 저장 위치를 생성하지 못했습니다.")
                self._camera_media_uri = uri

            intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            from jnius import cast
            ClipData=autoclass("android.content.ClipData")
            intent.putExtra(MediaStore.EXTRA_OUTPUT,cast("android.os.Parcelable",uri))
            intent.setClipData(ClipData.newRawUri("receipt",uri))
            intent.addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION)
            intent.addFlags(Intent.FLAG_GRANT_WRITE_URI_PERMISSION)

            # Some camera apps need the URI permission explicitly granted.
            resolve_info = activity.getPackageManager().queryIntentActivities(intent, 0)
            for i in range(resolve_info.size()):
                info = resolve_info.get(i)
                package_name = info.activityInfo.packageName
                activity.grantUriPermission(
                    package_name,
                    uri,
                    Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                )

            # Keep the result callback on the Android activity.
            from android import activity as android_activity
            android_activity.bind(on_activity_result=self._camera_activity_result)
            self._camera_request_code = 0xCAFE
            self._camera_uri = uri
            self._camera_granted_packages = [
                resolve_info.get(i).activityInfo.packageName
                for i in range(resolve_info.size())
            ]

            activity.startActivityForResult(intent, self._camera_request_code)

        except Exception as e:
            media_uri = getattr(self, "_camera_media_uri", None)
            if media_uri is not None:
                try:
                    context.getContentResolver().delete(media_uri, None, None)
                except Exception:
                    pass
                self._camera_media_uri = None
            message=str(e)
            if "meta-data" in message or "provider" in message.lower():
                message="APK에 카메라 FileProvider 설정이 없습니다. 동봉된 Android XML과 buildozer 설정을 적용한 뒤 APK를 다시 빌드해 설치해 주세요."
            try:
                from android import activity as android_activity
                android_activity.unbind(on_activity_result=self._camera_activity_result)
            except Exception:
                pass
            Clock.schedule_once(lambda _dt,msg=message:show_message("카메라 오류",msg),0)

    def _camera_activity_result(self, requestCode, resultCode, intent):
        if requestCode != getattr(self, "_camera_request_code", -1):
            return

        try:
            from android import activity as android_activity
            android_activity.unbind(on_activity_result=self._camera_activity_result)
        except Exception:
            pass

        try:
            from jnius import autoclass
            Intent = autoclass("android.content.Intent")
            uri = getattr(self, "_camera_uri", None)

            # Release temporary URI permissions after the camera returns.
            if uri is not None:
                for package_name in getattr(self, "_camera_granted_packages", []):
                    try:
                        App.get_running_app().root_window
                        from jnius import autoclass as _autoclass
                        PythonActivity = _autoclass("org.kivy.android.PythonActivity")
                        PythonActivity.mActivity.revokeUriPermission(
                            uri,
                            Intent.FLAG_GRANT_READ_URI_PERMISSION | Intent.FLAG_GRANT_WRITE_URI_PERMISSION,
                        )
                    except Exception:
                        pass

            media_uri = getattr(self, "_camera_media_uri", None)
            if media_uri is not None:
                resolver = autoclass("org.kivy.android.PythonActivity").mActivity.getContentResolver()
                try:
                    if resultCode == -1:
                        import shutil
                        descriptor = resolver.openFileDescriptor(media_uri, "r")
                        if descriptor is None:
                            raise RuntimeError("촬영한 사진을 읽을 수 없습니다.")
                        try:
                            fd = descriptor.detachFd()
                        finally:
                            descriptor.close()
                        with os.fdopen(fd, "rb") as source, open(self.camera_path, "wb") as target:
                            shutil.copyfileobj(source, target)
                finally:
                    resolver.delete(media_uri, None, None)
                    self._camera_media_uri = None
            if resultCode == -1:
                Clock.schedule_once(lambda _dt:self._camera_completed(self.camera_path),0)
            else:
                Clock.schedule_once(lambda _dt:setattr(self.info,"text","촬영이 취소되었습니다."),0)
        except Exception as e:
            show_message("카메라 오류", f"촬영 결과를 처리하지 못했습니다.\n{e}")

    def _camera_completed(self, filepath):
        try:
            path = filepath or self.camera_path
            if path and os.path.isfile(path) and os.path.getsize(path) > 0:
                self.camera_path = path
                self.closed = True
                self.on_capture(path)
                return
            self.info.text = "촬영이 취소되었거나 사진이 저장되지 않았습니다."
        except Exception as e:
            show_message("카메라 오류", f"촬영한 사진을 처리하지 못했습니다.\n{e}")

    def take_picture_pc(self):
        show_message("사진 선택","PC에서는 내 파일에서 영수증 이미지를 선택해 주세요.")

    def close(self, *_):
        if self.closed:
            return
        self.closed = True
        self.on_close()


class CameraScreen(Screen):
    def __init__(self, **kwargs):
        super().__init__(**kwargs)
        self.build_ui()

    def build_ui(self):
        self.clear_widgets()
        main = add_page_layout()
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("영수증 스캔", 22, True, size_hint_y=None, height=dp(44)))

        count = len(SESSION_STATE.get("receipts", []))
        self.status = make_label(
            f"현재 영수증 {count}개",
            14, color=COLOR_MUTED, size_hint_y=None, height=dp(28)
        )
        main.add_widget(self.status)

        sample = make_primary_button("[테스트] 샘플 영수증 추가", size_hint_y=None, height=dp(50))
        sample.bind(on_press=self.load_sample)
        main.add_widget(sample)

        camera_btn = make_button("카메라 열기", size_hint_y=None, height=dp(50))
        camera_btn.bind(on_press=self.open_camera)
        main.add_widget(camera_btn)

        file_btn = make_button("📁 내 파일 / 갤러리에서 선택", size_hint_y=None, height=dp(50))
        file_btn.bind(on_press=self.open_file)
        main.add_widget(file_btn)

        settlement_btn = make_primary_button(
            "현재 영수증들로 정산하기",
            size_hint_y=None, height=dp(52)
        )
        settlement_btn.bind(on_press=lambda *_: setattr(self.manager, "current", "settle"))
        main.add_widget(settlement_btn)

        self.receipt_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(8))
        self.receipt_box.bind(minimum_height=self.receipt_box.setter("height"))
        receipt_scroll = ScrollView(size_hint_y=None, height=dp(180))
        receipt_scroll.add_widget(self.receipt_box)
        main.add_widget(receipt_scroll)

        cancel = make_button("취소 및 홈으로", size_hint_y=None, height=dp(46))
        cancel.bind(on_press=lambda *_: setattr(self.manager, "current", "home"))
        main.add_widget(cancel)

        main.add_widget(Widget())
        self.add_widget(main)
        self.render_receipts()

    def render_receipts(self):
        self.receipt_box.clear_widgets()
        receipts = SESSION_STATE.get("receipts", [])
        if not receipts:
            self.receipt_box.add_widget(make_label("아직 추가한 영수증이 없습니다.", size_hint_y=None, height=dp(40),
                                                   halign="center"))
            return
        for i, receipt in enumerate(receipts, 1):
            card = Card(size_hint_y=None, height=dp(62))
            line = BoxLayout()
            line.add_widget(make_label(f"영수증 {i}", 15, True, size_hint_x=0.35))
            line.add_widget(make_label(f"{receipt['total']:,}원", 15, True, size_hint_x=0.45,
                                       halign="right", valign="middle"))
            delete = make_button("삭제", size_hint_x=None, width=dp(55))
            delete.bind(on_press=lambda *_x, idx=i-1: self.remove_receipt(idx))
            line.add_widget(delete)
            card.add_widget(line)
            self.receipt_box.add_widget(card)

    def remove_receipt(self, index):
        del SESSION_STATE["receipts"][index]
        self.build_ui()

    def load_sample(self, *_):
        SESSION_STATE["receipts"].append({
            "items": [
                {"item": "삼겹살 2인분", "price": 36000, "qty": 2},
                {"item": "차돌된장찌개", "price": 8000, "qty": 1},
                {"item": "공기밥", "price": 2000, "qty": 2},
                {"item": "음료수", "price": 2000, "qty": 1},
            ],
            "total": 48000,
        })
        self.build_ui()

    def open_camera(self, *_):
        content_holder = BoxLayout(orientation="vertical")
        popup = Popup(title="카메라", title_font=FONT_BOLD, content=content_holder, size_hint=(0.95, 0.88))

        def captured(path):
            popup.dismiss()
            self.process_image_file(path)

        def closed():
            popup.dismiss()

        camera = PhoneCamera(on_capture=captured, on_close=closed)
        content_holder.add_widget(camera)
        popup.open()

    def open_file(self, *_):
        if platform == "android":
            try:
                from jnius import autoclass
                from android import activity

                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                Intent = autoclass("android.content.Intent")

                intent = Intent(Intent.ACTION_GET_CONTENT)
                intent.setType("image/*")
                intent.addCategory(Intent.CATEGORY_OPENABLE)
                activity.bind(on_activity_result=self.on_file_result)
                PythonActivity.mActivity.startActivityForResult(intent, 0x9999)
                return
            except Exception as e:
                show_message("오류", f"파일 선택기를 열지 못했습니다.\n{e}")
                return

        self.open_pc_file_chooser()

    def on_file_result(self, requestCode, resultCode, intent):
        if requestCode != 0x9999:
            return

        from android import activity
        activity.unbind(on_activity_result=self.on_file_result)

        if resultCode == -1 and intent is not None:
            try:
                from jnius import autoclass
                PythonActivity = autoclass("org.kivy.android.PythonActivity")
                context = PythonActivity.mActivity.getApplicationContext()
                uri = intent.getData()
                content_resolver = context.getContentResolver()
                input_stream = content_resolver.openInputStream(uri)

                dest_path = os.path.join(
                    App.get_running_app().user_data_dir,
                    f"selected_receipt_{int(time.time())}.jpg",
                )

                output_stream = open(dest_path, "wb")
                buffer = bytearray(1024)
                while True:
                    length = input_stream.read(buffer)
                    if length <= 0:
                        break
                    output_stream.write(buffer[:length])

                output_stream.close()
                input_stream.close()

                if os.path.isfile(dest_path) and os.path.getsize(dest_path) > 0:
                    self.process_image_file(dest_path)
                    return

            except Exception as e:
                show_message("파일 오류", f"파일을 불러오는 데 실패했습니다.\n{e}")

        self.status.text = "사진 선택이 취소되었습니다."

    def open_pc_file_chooser(self):
        chooser = FileChooserListView(
            path=os.getcwd(),
            filters=["*.jpg", "*.jpeg", "*.png", "*.JPG", "*.JPEG", "*.PNG"],
        )
        content = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(8))
        buttons = BoxLayout(size_hint_y=None, height=dp(48), spacing=dp(8))
        select = make_primary_button("선택")
        cancel = make_button("취소")
        buttons.add_widget(select)
        buttons.add_widget(cancel)
        content.add_widget(chooser)
        content.add_widget(buttons)

        popup = Popup(
            title="영수증 이미지 선택",
            title_font=FONT_BOLD,
            content=content,
            size_hint=(0.95, 0.85),
        )

        def do_select(*_):
            if not chooser.selection:
                show_message("경고", "이미지 파일을 선택해 주세요.")
                return
            path = chooser.selection[0]
            popup.dismiss()
            self.process_image_file(path)

        select.bind(on_press=do_select)
        cancel.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

    def process_image_file(self, path):
        if not os.path.exists(path):
            show_message("오류", "이미지 파일을 찾을 수 없습니다.")
            return
        if not SESSION_STATE.get("token"):
            show_message("로그인 필요", "OCR을 사용하려면 먼저 로그인하세요.")
            return
        if getattr(self, "_ocr_busy", False):
            return
        self._ocr_busy = True
        self.status.text = "서버에서 영수증을 읽는 중입니다..."
        token = SESSION_STATE["token"]
        generation = SESSION_STATE.get("generation", 0)
        def completed(data=None, error=None):
            self._ocr_busy = False
            if generation != SESSION_STATE.get("generation", 0):
                return
            if error:
                self.status.text = "인식 실패: 다시 시도하거나 직접 입력하세요."
                show_message("OCR 오류", error)
                return
            if not data or not data.get("items"):
                self.status.text = "인식 실패: 다시 시도하거나 직접 입력하세요."
                show_message("OCR 실패", "영수증 품목을 인식하지 못했습니다. 직접 입력할 수 있습니다.")
                self.review_receipt(data or {"items": [], "total": 0})
                return
            self.review_receipt(data)
        def worker():
            try:
                data = _multipart_upload_image(path, token)
                Clock.schedule_once(lambda _dt, value=data: completed(data=value), 0)
            except Exception as exc:
                Clock.schedule_once(lambda _dt, msg=str(exc): completed(error=msg), 0)
        threading.Thread(target=worker, daemon=True).start()



    def review_receipt(self, data, index=None):
        layout = BoxLayout(orientation="vertical", padding=dp(10), spacing=dp(8))
        layout.add_widget(make_label(
            "품목명 | 수량 | 품목 합계 금액\n한 줄에 한 품목. 할인은 품목 금액에 반영하세요.",
            13, size_hint_y=None, height=dp(48)
        ))
        editor = make_text_input(
            text="\n".join(
                f"{x.get('item','')} | {x.get('qty',1)} | {x.get('price',0)}"
                for x in (data or {}).get("items", [])
            ),
            multiline=True,
        )
        total = make_text_input(
            text=str((data or {}).get("total", 0)),
            hint_text="영수증 총액",
            multiline=False,
            size_hint_y=None,
            height=dp(44),
        )
        layout.add_widget(editor)
        layout.add_widget(total)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        save = make_primary_button("확인 후 저장")
        cancel = make_button("취소")
        actions.add_widget(save)
        actions.add_widget(cancel)
        layout.add_widget(actions)
        popup = Popup(title="영수증 인식 결과 수정", title_font=FONT_BOLD, content=layout, size_hint=(.96, .9))

        def commit(*_):
            try:
                items = []
                for line in editor.text.splitlines():
                    if not line.strip():
                        continue
                    parts = [x.strip() for x in line.rsplit("|", 2)]
                    if len(parts) != 3:
                        raise ValueError("각 줄은 품목명 | 수량 | 금액 형식이어야 합니다.")
                    name, qty, price = parts
                    qty, price = int(qty), int(price.replace(",", ""))
                    if not name or not 1 <= qty <= 10000 or not 0 <= price <= 1_000_000_000:
                        raise ValueError("품목명/수량/금액을 확인해 주세요.")
                    items.append({"item": name, "qty": qty, "price": price})
                amount = int(total.text.replace(",", ""))
                if not items or not 0 < amount <= 1_000_000_000:
                    raise ValueError("영수증 총액을 확인해 주세요.")
                if sum(x["price"] for x in items) != amount:
                    raise ValueError("품목 합계와 영수증 총액이 같아야 합니다.")
                receipt = {"items": items, "total": amount}
                if index is None:
                    SESSION_STATE["receipts"].append(receipt)
                else:
                    SESSION_STATE["receipts"][index] = receipt
                popup.dismiss()
                self.build_ui()
            except (ValueError, IndexError) as exc:
                show_message("입력 확인", str(exc))

        save.bind(on_press=commit)
        cancel.bind(on_press=lambda *_: popup.dismiss())
        popup.open()

# ============================================================
# SETTLEMENT
# ============================================================
class QtyInput(TextInput):
    max_value = NumericProperty(1)

    def __init__(self, **kwargs):
        super().__init__(input_filter="int", multiline=False, **kwargs)
        self.font_name = FONT_REGULAR
        self.foreground_color = COLOR_TEXT
        self.background_color = COLOR_SURFACE
        self.bind(focus=self._focus_changed)

    def _focus_changed(self, _, focused):
        if not focused:
            self.normalize()

    def normalize(self):
        try:
            value = int(self.text)
        except Exception:
            value = 1
        value = max(1, min(value, max(1, int(self.max_value))))
        self.text = str(value)


class MemberRow(BoxLayout):
    def __init__(self,member,max_qty,on_changed,**kwargs):
        super().__init__(orientation="horizontal",size_hint_y=None,height=dp(54),spacing=dp(6),**kwargs)
        self.member=member
        self.max_qty=int(max_qty)
        self.on_changed=on_changed
        self._updating=False
        self.checkbox=CheckBox()  # state only; no tiny checkbox touch target
        self.name_button=make_button(member)
        self.name_button.bind(on_release=self._toggle)
        self.add_widget(self.name_button)
        self.minus=make_button("-",bold=True,size_hint_x=None,width=dp(46))
        self.minus.bind(on_release=lambda *_:self._step(-1))
        self.add_widget(self.minus)
        self.qty=make_label("0",17,True,size_hint_x=None,width=dp(32))
        self.add_widget(self.qty)
        self.plus=make_button("+",bold=True,size_hint_x=None,width=dp(46))
        self.plus.bind(on_release=lambda *_:self._step(1))
        self.add_widget(self.plus)
        self._paint()
    def _paint(self):
        active=self.checkbox.active
        self.name_button.text=("선택 · " if active else "")+self.member
        self.name_button._tone.rgba=COLOR_PRIMARY if active else COLOR_PRIMARY_LIGHT
        self.name_button.color=(1,1,1,1) if active else COLOR_TEXT
        self.minus.disabled=not active
    def _toggle(self,*_):
        self._step(-self.selected_qty() if self.checkbox.active else 1)
    def _step(self,delta):
        old=self.selected_qty()
        screen=getattr(self,"settle_screen",None)
        peers=screen.member_rows.get(self.item_key,[]) if screen else []
        remaining=self.max_qty-sum(r.selected_qty() for r in peers if r is not self)
        value=max(0,min(old+delta,remaining,self.max_qty))
        if delta>0 and value==old:
            show_toast("남은 수량이 없습니다. 다른 참여자 수량을 먼저 줄여 주세요.")
            return
        self.set_value(value)
        self.on_changed()
    def set_value(self,value):
        value=max(0,min(int(value),self.max_qty))
        self.checkbox.active=value>0
        self.qty.text=str(value)
        self._paint()
    def selected_qty(self):
        return int(self.qty.text) if self.checkbox.active else 0
    def set_max_allowed(self,allowed):
        if self.selected_qty()>allowed:self.set_value(allowed)
    def set_check_disabled(self,disabled):
        self.name_button.disabled=bool(disabled and not self.checkbox.active)



class SettleScreen(Screen):
    def on_enter(self):
        self.build_ui()

    def build_ui(self):
        self.clear_widgets()
        self.name_inputs = []
        self.member_rows = {}
        self.current_receipts = SESSION_STATE.get("receipts", [])

        outer=add_page_layout()
        body_scroll=ScrollView(do_scroll_x=False)
        main=BoxLayout(orientation="vertical",size_hint_y=None,spacing=dp(10))
        main.bind(minimum_height=main.setter("height"))
        body_scroll.add_widget(main)
        outer.add_widget(body_scroll)
        main.add_widget(add_logo_header(self))
        main.add_widget(make_label("영수증 정산", 22, True, size_hint_y=None, height=dp(44)))

        if not self.current_receipts:
            main.add_widget(make_label(
                "인식된 영수증이 없습니다.\n영수증을 먼저 추가해 주세요.",
                halign="center", size_hint_y=None, height=dp(70)
            ))
            go = make_primary_button("영수증 추가", size_hint_y=None, height=dp(50))
            go.bind(on_press=lambda *_: setattr(self.manager, "current", "camera"))
            main.add_widget(go)
            main.add_widget(Widget())
            self.add_widget(outer)
            return

        main.add_widget(make_label("입금받을 계좌 정보", 17, True, size_hint_y=None, height=dp(34)))

        account_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(45), spacing=dp(8))
        self.bank_input = Spinner(
            text="토스뱅크",
            values=("토스뱅크", "카카오페이"),
            option_cls=KoreanSpinnerOption,
            font_name=FONT_REGULAR,
            font_size=dp(15),
            color=COLOR_TEXT,
            background_normal="",
            background_color=COLOR_SURFACE,
            size_hint_x=0.38,
        )
        self.acc_input = make_text_input(
            hint_text="계좌번호",
            multiline=False,
            size_hint_x=0.62,
        )
        account_row.add_widget(self.bank_input)
        account_row.add_widget(self.acc_input)
        main.add_widget(account_row)

        main.add_widget(make_label("정산 참여자", 17, True, size_hint_y=None, height=dp(34)))

        self.member_box = BoxLayout(orientation="vertical", size_hint_y=None, spacing=dp(7))
        self.member_box.bind(minimum_height=self.member_box.setter("height"))

        self.add_member_field()

        member_scroll = ScrollView(size_hint_y=None, height=dp(170))
        member_scroll.add_widget(self.member_box)
        main.add_widget(member_scroll)

        member_actions = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(7))
        add_name_btn = make_button("+ 이름 추가", size_hint_x=0.45)
        add_name_btn.bind(on_press=lambda *_: self.add_member_field())
        apply_names_btn = make_primary_button("참여자 적용", size_hint_x=0.55)
        apply_names_btn.bind(on_press=self.apply_members)
        member_actions.add_widget(add_name_btn)
        member_actions.add_widget(apply_names_btn)
        main.add_widget(member_actions)

        friends_label = make_label("내 친구 · 누르면 빈 이름 칸에 추가", 13, True,
                                   color=COLOR_MUTED, size_hint_y=None, height=dp(24))
        main.add_widget(friends_label)

        self.friend_quick_box = BoxLayout(size_hint_y=None, height=dp(40), spacing=dp(6))
        main.add_widget(self.friend_quick_box)
        self.render_friend_quick_add()

        total = sum(r["total"] for r in self.current_receipts)
        total_card = Card(size_hint_y=None, height=dp(66))
        total_card.add_widget(make_label(f"전체 영수증 {len(self.current_receipts)}개", 13, False,
                                         color=COLOR_MUTED, size_hint_y=None, height=dp(22)))
        total_card.add_widget(make_label(f"총 {total:,}원", 20, True, size_hint_y=None, height=dp(30)))
        main.add_widget(total_card)

        self.items_scroll = ScrollView(size_hint_y=None,height=dp(460),do_scroll_x=False)
        self.items_container = BoxLayout(
            orientation="vertical", size_hint_y=None,
            spacing=dp(12), padding=[0, dp(3), 0, dp(3)]
        )
        self.items_container.bind(minimum_height=self.items_container.setter("height"))
        self.items_scroll.add_widget(self.items_container)
        main.add_widget(self.items_scroll)

        action_row = BoxLayout(size_hint_y=None, height=dp(52), spacing=dp(8))
        add_receipt = make_button("+ 영수증 추가", size_hint_x=0.38)
        add_receipt.bind(on_press=lambda *_: setattr(self.manager, "current", "camera"))
        settle_btn = make_primary_button("정산 링크 복사", size_hint_x=0.62)
        self.settle_button=settle_btn
        settle_btn.bind(on_press=lambda *_: self.process_settlement())
        action_row.add_widget(add_receipt)
        action_row.add_widget(settle_btn)
        outer.add_widget(action_row)

        self.add_widget(outer)

    def apply_members(self, *_):
        for inp in self.name_inputs:
            inp.focus = False

        entered=[inp.text.strip() for inp in self.name_inputs if inp.text.strip()]
        if len(entered)!=len(set(entered)):
            show_message("중복 이름","동명이인은 이름 뒤에 숫자를 붙여 구분해 주세요.")
            return
        members = self.collect_members()

        if not members:
            show_message("참여자 입력", "참여자 이름을 한 명 이상 입력해 주세요.")
            return

        self.render_menu_items()
        Clock.schedule_once(lambda *_: self._focus_items_area(), 0)

    def _focus_items_area(self):
        if hasattr(self, "items_scroll"):
            self.items_scroll.scroll_y = 1

    def add_member_field(self, preset=""):
        row = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(7))

        index = len(self.name_inputs) + 1
        inp = make_text_input(
            hint_text=f"{index}번째 이름",
            text=preset,
            multiline=False,
        )
        row.member_input = inp
        self.name_inputs.append(inp)

        paste_btn = make_button("붙여넣기", size_hint_x=None, width=dp(78))
        paste_btn.bind(on_press=lambda *_: self.paste_into_input(inp))

        minus = make_button("삭제", bold=True, size_hint_x=None, width=dp(52))
        minus.bind(on_press=lambda *_: self.remove_member_field(inp))

        if len(self.name_inputs) == 1:
            minus.disabled = True

        row.add_widget(inp)
        row.add_widget(paste_btn)
        row.add_widget(minus)

        # + 버튼은 마지막 줄에만 하나 두지 않고 이름영역 상단에 따로 배치하지 않기 위해
        # 첫 줄 아래에 별도 add 버튼을 추가합니다.
        self.member_box.add_widget(row)

    def paste_into_input(self, inp):
        try:
            text = Clipboard.paste() or ""
        except Exception as e:
            show_message("붙여넣기 실패", str(e))
            return
        text = text.replace("\n", " ").strip()
        if text:
            inp.text = text
            inp.focus = False

    def remove_member_field(self, inp):
        if len(self.name_inputs) <= 1:
            inp.text = ""
            return
        index = self.name_inputs.index(inp)
        self.name_inputs.pop(index)

        for child in list(self.member_box.children):
            if getattr(child, "member_input", None) is inp:
                self.member_box.remove_widget(child)
                break
        self.render_menu_items()

    def render_friend_quick_add(self):
        self.friend_quick_box.clear_widgets()
        friends = SESSION_STATE.get("friends", [])
        if not friends:
            self.friend_quick_box.add_widget(make_label("친구 없음", 12, color=COLOR_MUTED))
            return

        for friend in friends[:5]:
            btn = make_button(friend["name"], size_hint_x=None, width=dp(82))
            btn.bind(on_press=lambda _btn, name=friend["name"]: self.fill_next_member(name))
            self.friend_quick_box.add_widget(btn)

    def fill_next_member(self, name):
        for inp in self.name_inputs:
            if not inp.text.strip():
                inp.text = name
                return
        self.add_member_field(name)

    def collect_members(self):
        members = []
        for inp in self.name_inputs:
            name = inp.text.strip()
            if name and name not in members:
                members.append(name)
        return members

    def render_menu_items(self):
        members = self.collect_members()
        saved={(key,row.member):row.selected_qty() for key,rows in self.member_rows.items() for row in rows}
        self.items_container.clear_widgets()
        self.member_rows = {}
        self.item_status = {}

        if not members:
            self.items_container.add_widget(make_label(
                "위의 이름 칸에 참여자를 추가해 주세요.",
                size_hint_y=None, height=dp(48), halign="center"
            ))
            return

        for receipt_index, receipt in enumerate(self.current_receipts):
            items = receipt["items"]
            receipt_card = Card(
                size_hint_y=None,
                height=dp(58 + sum(48 + 44 * len(members) for _ in items))
            )
            receipt_card.bind(minimum_height=receipt_card.setter("height"))
            receipt_card.add_widget(make_label(
                f"영수증 {receipt_index + 1} · {receipt['total']:,}원",
                16, True, size_hint_y=None, height=dp(28)
            ))

            for item_index, item in enumerate(items):
                max_qty = max(1, int(item["qty"]))
                sub = Card(size_hint_y=None, height=dp(50 + 44 * len(members)))
                sub.bind(minimum_height=sub.setter("height"))
                sub.add_widget(make_label(
                    f"{item['item']}  {item['price']:,}원 · {max_qty}개",
                    14, True, size_hint_y=None, height=dp(26)
                ))

                rows = []
                for member in members:
                    row = MemberRow(member, max_qty, self.recalculate_limits)
                    row.settle_screen=self
                    row.item_key=(receipt_index,item_index)
                    row.set_value(saved.get((row.item_key,member),0))
                    rows.append(row)
                    sub.add_widget(row)

                key = (receipt_index, item_index)
                self.member_rows[key] = rows
                controls=BoxLayout(size_hint_y=None,height=dp(44),spacing=dp(8))
                status=make_label("",13,color=COLOR_MUTED)
                self.item_status[key]=status
                controls.add_widget(status)
                equal=make_button("균등 배분",size_hint_x=None,width=dp(100))
                equal.bind(on_release=lambda _btn,k=key:self.equal_allocate(k))
                controls.add_widget(equal)
                sub.add_widget(controls)
                receipt_card.add_widget(sub)

            self.items_container.add_widget(receipt_card)

        self.recalculate_limits()

    def equal_allocate(self,key):
        rows=self.member_rows[key]
        qty=rows[0].max_qty
        q,r=divmod(qty,len(rows))
        for i,row in enumerate(rows):row.set_value(q+(i<r))
        self.recalculate_limits()

    def recalculate_limits(self):
        for key, rows in self.member_rows.items():
            max_qty = rows[0].max_qty if rows else 1
            selected = sum(r.selected_qty() for r in rows)

            if selected > max_qty:
                overflow = selected - max_qty
                for row in reversed(rows):
                    if overflow <= 0:
                        break
                    if not row.checkbox.active:
                        continue
                    current = row.selected_qty()
                    reduce_by = min(max(0, current - 1), overflow)
                    if reduce_by:
                        row._updating = True
                        row.qty.text = str(current - reduce_by)
                        row._updating = False
                        overflow -= reduce_by

                selected = sum(r.selected_qty() for r in rows)

            if key in getattr(self,"item_status",{}):
                self.item_status[key].text=f"배분 {selected}/{max_qty} · 남음 {max(0,max_qty-selected)}"
                self.item_status[key].color=COLOR_SUCCESS if selected==max_qty else COLOR_MUTED
            for row in rows:
                row.plus.disabled=selected>=max_qty
                own = row.selected_qty()
                other = selected - own
                remaining = max_qty - other
                if row.checkbox.active:
                    row.set_max_allowed(max(1, remaining))
                    row.set_check_disabled(False)
                else:
                    row.set_check_disabled(remaining <= 0)

    def process_settlement(self):
        if getattr(self,"_settle_busy",False):return
        if not SESSION_STATE["current_user"]:
            show_message("로그인 필요", "정산 링크를 만들려면 먼저 로그인해 주세요.")
            self.manager.current = "login"
            return

        bank = self.bank_input.text.strip()
        account = self.acc_input.text.strip()
        if not bank or not account:
            show_message("경고", "입금받을 계좌 정보를 입력해 주세요.")
            return

        members = self.collect_members()
        if not members:
            show_message("경고", "참여자 이름을 한 명 이상 입력해 주세요.")
            return

        if not self.member_rows:
            show_message("참여자 적용", "참여자 이름을 입력한 뒤 '참여자 적용'을 눌러 주세요.")
            return

        member_totals = {m: Fraction(0) for m in members}
        expected_total = sum(int(r["total"]) for r in self.current_receipts)
        item_total = sum(int(i["price"]) for r in self.current_receipts for i in r["items"])
        if item_total != expected_total:
            show_message("총액 확인", "품목 금액 합계와 영수증 총액을 일치시켜 주세요.")
            return
        if any(row.member not in members for rows in self.member_rows.values() for row in rows):
            show_message("참여자 적용", "참여자가 변경되었습니다. 참여자 적용을 다시 눌러 주세요.")
            return
        allocated = []

        for key, rows in self.member_rows.items():
            receipt_index, item_index = key
            item = self.current_receipts[receipt_index]["items"][item_index]
            price = int(item["price"])
            max_qty = int(item["qty"])

            shares = {r.member: r.selected_qty() for r in rows if r.selected_qty() > 0}
            total_selected = sum(shares.values())
            allocated.append((total_selected, max_qty))

            if total_selected != max_qty:
                show_message(
                    "배분 필요",
                    f"영수증 {receipt_index + 1}의 '{item['item']}' 수량을\n"
                    f"참여자에게 모두 배분해 주세요. ({total_selected}/{max_qty})",
                )
                return

            for member, share in shares.items():
                member_totals[member] += Fraction(price * share, total_selected)

        final_totals = {m: int(v) for m, v in member_totals.items()}
        remainder = expected_total - sum(final_totals.values())
        ranked = sorted(members, key=lambda name: member_totals[name] - final_totals[name], reverse=True)
        for name in ranked[:remainder]:
            final_totals[name] += 1

        friend_map = {f["name"]: f["id"] for f in SESSION_STATE.get("friends", [])}
        participants = [
            {
                "name": m,
                "amount": int(final_totals[m]),
                "user_id": friend_map.get(m),
            }
            for m in members
            if final_totals[m] > 0
        ]

        receipts_payload = [
            {
                "total_amount": int(receipt["total"]),
                "items": receipt["items"],
            }
            for receipt in self.current_receipts
        ]

        payload_identity=json.dumps([bank,account,participants,receipts_payload],ensure_ascii=False,sort_keys=True)
        if getattr(self,"_request_identity",None)!=payload_identity:
            self._request_identity=payload_identity
            self._request_id=uuid.uuid4().hex
        self._settle_busy=True
        self.settle_button.disabled=True
        self.settle_button.text="링크 만드는 중..."
        async_api(
            "POST", "/api/settlements",
            {
                "request_id":self._request_id,
                "bank": bank,
                "account": account,
                "participants": participants,
                "receipts": receipts_payload,
            },
            self.settlement_created,
            self.settlement_failed,
        )

    def settlement_failed(self,error):
        self._settle_busy=False
        self.settle_button.disabled=False
        self.settle_button.text="정산 링크 복사"
        show_message("정산 생성 실패",error)

    def settlement_created(self, data):
        self._settle_busy=False
        self.settle_button.disabled=False
        self.settle_button.text="정산 링크 복사"
        share_url = data["share_url"]
        Clipboard.copy(share_url)

        total = data["total_amount"]
        SESSION_STATE["history"].append({
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "total": total,
            "members": [p["name"] for p in data["participants"]],
            "count": len(data["receipts"]),
        })

        # 결과 팝업 없이 링크를 바로 클립보드에 복사
        show_toast(f"정산 링크가 복사되었습니다.\n{total:,}원")
        SESSION_STATE["receipts"] = []
        self.manager.current = "home"


# ============================================================
# SERVER LOAD HELPERS
# ============================================================
def load_friends_from_server():
    if not SESSION_STATE.get("token"):
        return

    def success(data):
        SESSION_STATE["friends"] = data
        screen = App.get_running_app().root.current
        if screen == "friends":
            App.get_running_app().root.get_screen("friends").render_friends()
        elif screen == "settle":
            App.get_running_app().root.get_screen("settle").render_friend_quick_add()

    async_api("GET", "/api/friends", None, success, lambda _err: None)


def load_notifications_from_server():
    if not SESSION_STATE.get("token"):
        return

    def success(data):
        old_ids = {n["id"] for n in SESSION_STATE.get("notifications", [])}
        SESSION_STATE["notifications"] = data

        new_payment = next(
            (n for n in data if n["id"] not in old_ids and n["kind"] == "payment_received"),
            None,
        )
        app = App.get_running_app()
        if new_payment:
            app.notify_payment(new_payment)

        root = app.root
        if root.current == "notifications":
            root.get_screen("notifications").render()

    async_api("GET", "/api/notifications", None, success, lambda _err: None)


def load_history_from_server():
    if not SESSION_STATE.get("token"):
        return

    def success(data):
        SESSION_STATE["history"] = data
        root = App.get_running_app().root
        if root.current == "home":
            root.get_screen("home").on_enter()

    async_api("GET", "/api/settlements?mine=1", None, success, lambda _err: None)


# ============================================================
# APP
# ============================================================
class DutchPayApp(App):
    def build(self):
        self.title = "영수증 더치페이"
        sm = ScreenManager()
        sm.add_widget(HomeScreen(name="home"))
        sm.add_widget(LoginScreen(name="login"))
        sm.add_widget(SignupScreen(name="signup"))
        sm.add_widget(MyPageScreen(name="mypage"))
        sm.add_widget(FriendsScreen(name="friends"))
        sm.add_widget(NotificationsScreen(name="notifications"))
        sm.add_widget(CameraScreen(name="camera"))
        sm.add_widget(SettleScreen(name="settle"))
        Window.bind(on_keyboard=self.handle_back_key)
        return sm

    def handle_back_key(self, window, key, *args):
        if key == 27 and self.root and self.root.current != "home":
            # Let an open popup handle Back before navigating the page.
            from kivy.uix.modalview import ModalView
            for child in Window.children:
                if isinstance(child, ModalView):
                    if child.auto_dismiss:
                        child.dismiss()
                    return True
            self.root.transition.direction = "right"
            self.root.current = "home"
            return True
        return False

    def on_stop(self):
        Window.unbind(on_keyboard=self.handle_back_key)
        event = getattr(self, "_notification_event", None)
        if event is not None:
            event.cancel()

    def on_start(self):
        self._notification_event = None
        if SESSION_STATE["current_user"]:
            self.start_notification_polling()

    def start_notification_polling(self):
        if self._notification_event is not None:
            self._notification_event.cancel()
        self._notification_event = Clock.schedule_interval(
            lambda _dt: load_notifications_from_server(), 15
        )

    def notify_payment(self, notification):
        message = notification["message"]
        show_toast(message)

        if plyer_notification is not None:
            try:
                plyer_notification.notify(
                    title="더치페이 입금 알림",
                    message=message,
                    app_name="더치페이",
                    timeout=5,
                )
            except Exception:
                pass


if __name__ == "__main__":
    DutchPayApp().run()