import os
import uuid
import copy
import re
import datetime
import json
import tempfile
import time
import threading
import urllib.parse

import requests
from kivy.app import App
from kivy.clock import Clock
from kivy.core.clipboard import Clipboard
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
# GOOGLE VISION
# ============================================================
# ============================================================
# SESSION
# ============================================================
SESSION_STATE = {
    "generation": 0,
    "draft": {},
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

    try:
        response = requests.request(
            method,
            url,
            json=json_data,
            headers=headers,
            timeout=timeout,
        )
    except requests.RequestException as e:
        raise RuntimeError(f"서버 연결 실패\n{url}\n{e}")

    try:
        data = response.json()
    except Exception:
        raise RuntimeError("서버가 JSON 대신 다른 응답을 반환했습니다. 배포 상태를 확인하세요.")

    if response.status_code >= 400:
        raise RuntimeError(data.get("error", f"서버 오류 ({response.status_code})"))
    return data


def async_api(method, path, json_data, on_success, on_error, auth=True):
    token = SESSION_STATE.get('token')
    generation = SESSION_STATE['generation']
    def dispatch(callback, value):
        if generation == SESSION_STATE['generation']:
            callback(value)
    def worker():
        try:
            result = api_request(method, path, json_data, auth=auth, token=token)
            Clock.schedule_once(lambda _dt, result=result: dispatch(on_success, result), 0)
        except Exception as exc:
            Clock.schedule_once(lambda _dt, msg=str(exc): dispatch(on_error, msg), 0)
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


def make_button(text="", bold=False, **kwargs):
    return Button(
        text=text,
        font_name=FONT_BOLD if bold else FONT_REGULAR,
        color=COLOR_TEXT,
        background_normal="",
        background_color=COLOR_PRIMARY_LIGHT,
        **kwargs,
    )


def make_primary_button(text="", **kwargs):
    return Button(
        text=text,
        font_name=FONT_BOLD,
        color=(1, 1, 1, 1),
        background_normal="",
        background_color=COLOR_PRIMARY,
        **kwargs,
    )


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
    content = BoxLayout(orientation="vertical", padding=dp(15), spacing=dp(12))
    content.add_widget(make_label(message, halign="center", valign="middle"))
    btn = make_primary_button("확인", size_hint_y=None, height=dp(45))
    content.add_widget(btn)
    popup = Popup(
        title=title,
        title_font=FONT_BOLD,
        content=content,
        size_hint=(0.88, 0.32),
        auto_dismiss=False,
    )
    btn.bind(on_press=lambda *_: popup.dismiss())
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
    header = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(62), spacing=dp(10))

    logo_box = BoxLayout(orientation="vertical", padding=[dp(14), dp(6)])
    with logo_box.canvas.before:
        Color(*COLOR_PRIMARY_DARK)
        bg = RoundedRectangle(radius=[dp(12)])
    logo_box.bind(pos=lambda obj, *_: setattr(bg, "pos", obj.pos))
    logo_box.bind(size=lambda obj, *_: setattr(bg, "size", obj.size))
    logo_box.add_widget(make_label("DUTCH", 10, True, color=(0.78, 0.83, 1, 1),
                                   size_hint_y=0.4, halign="left", valign="top"))
    logo_box.add_widget(make_label("더치페이", 20, True, color=(1, 1, 1, 1),
                                   size_hint_y=0.6, halign="left", valign="top"))

    def logo_home(*_):
        screen.manager.current = "home"

    logo_button = Button(
        background_normal="",
        background_color=(0, 0, 0, 0),
        text="",
        size_hint_x=1,
    )
    logo_button.add_widget(logo_box)
    logo_button.bind(on_press=logo_home)

    login_text = "마이페이지" if SESSION_STATE["current_user"] else "로그인"
    user_button = make_button(login_text, bold=True, size_hint_x=None, width=dp(88))
    user_button.bind(on_press=lambda *_: setattr(
        screen.manager,
        "current",
        "mypage" if SESSION_STATE["current_user"] else "login",
    ))

    header.add_widget(logo_button)
    header.add_widget(user_button)
    return header


def add_page_layout():
    return BaseLayout(orientation="vertical", padding=dp(14), spacing=dp(11))


# ============================================================
# OCR
# ============================================================
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
            for item in history:
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
        SESSION_STATE["draft"] = {}
        SESSION_STATE["generation"] += 1
        self.manager.current = "camera"


# ============================================================
# LOGIN / SIGNUP
# ============================================================
class LoginScreen(Screen):
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
        pw = self.pw_input.text
        if not email or not pw:
            show_message("경고", "이메일과 비밀번호를 입력해 주세요.")
            return

        async_api(
            "POST", "/api/auth/login",
            {"email": email, "password": pw},
            self.login_success,
            lambda err: show_message("로그인 실패", err),
            auth=False,
        )

    def login_success(self, data):
        SESSION_STATE["generation"] += 1
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
        pw = self.pw_input.text
        if not name or not email or not pw:
            show_message("경고", "모든 항목을 입력해 주세요.")
            return

        async_api(
            "POST", "/api/auth/register",
            {"name": name, "email": email, "password": pw},
            lambda _data: self.signup_success(),
            lambda err: show_message("회원가입 실패", err),
            auth=False,
        )

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
        SESSION_STATE['generation'] += 1
        SESSION_STATE['history'] = []
        SESSION_STATE['receipts'] = []
        SESSION_STATE['draft'] = {}
        app = App.get_running_app()
        if getattr(app, '_notification_event', None):
            app._notification_event.cancel()
            app._notification_event = None
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
            if not n.get('read'):
                async_api('POST', f"/api/notifications/{n['id']}/read", {},
                          lambda _data, item=n: item.update(read=1), lambda _err: None)


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
            FileProvider = autoclass("androidx.core.content.FileProvider")

            activity = PythonActivity.mActivity
            context = activity.getApplicationContext()

            filename = os.path.join(
                App.get_running_app().user_data_dir,
                f"dutchpay_receipt_{int(time.time())}.jpg",
            )
            self.camera_path = filename

            # FileProvider is registered in AndroidManifest.xml.
            authority = context.getPackageName() + ".fileprovider"
            file_obj = File(filename)
            uri = FileProvider.getUriForFile(context, authority, file_obj)

            intent = Intent(MediaStore.ACTION_IMAGE_CAPTURE)
            intent.putExtra(MediaStore.EXTRA_OUTPUT, uri)
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
            show_message("카메라 오류", f"카메라를 실행하지 못했습니다.\n{e}")

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

            if resultCode == -1:
                Clock.schedule_once(lambda _dt: self._camera_completed(self.camera_path), 0)
            else:
                self.info.text = "촬영이 취소되었습니다."
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
        self.close()
        App.get_running_app().root.get_screen('camera').open_pc_file_chooser()

    def close(self, *_):
        if self.closed:
            return
        self.closed = True
        self.on_close()


class CameraScreen(Screen):
    def on_enter(self):
        self.build_ui()

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
        manual = make_button('영수증 직접 입력', size_hint_y=None, height=dp(44))
        manual.bind(on_press=lambda *_: self.review_receipt({'items': [], 'total': 0}))
        main.add_widget(manual)

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
            edit = make_button('수정', size_hint_x=None, width=dp(55))
            edit.bind(on_press=lambda *_x, idx=i-1: self.review_receipt(SESSION_STATE['receipts'][idx], idx))
            line.add_widget(edit)
            line.add_widget(delete)
            card.add_widget(line)
            self.receipt_box.add_widget(card)

    def remove_receipt(self, index):
        if not 0 <= index < len(SESSION_STATE["receipts"]):
            return
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
                    Clock.schedule_once(lambda _dt, path=dest_path: self.process_image_file(path), 0)
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
        if not SESSION_STATE.get('token'):
            show_message('로그인 필요', 'OCR을 사용하려면 먼저 로그인하세요.')
            return
        if getattr(self, '_ocr_busy', False):
            return
        self._ocr_busy = True
        self.status.text = '서버에서 영수증을 읽는 중입니다...'
        token, generation = SESSION_STATE['token'], SESSION_STATE['generation']
        def completed(data=None, error=None):
            self._ocr_busy = False
            if generation != SESSION_STATE['generation']:
                return
            if error:
                show_message('OCR 오류', error)
                self.status.text = '인식 실패: 다시 시도하거나 직접 입력하세요.'
            else:
                self.review_receipt(data)
        def worker():
            try:
                if os.path.getsize(path) > 10 * 1024 * 1024:
                    raise ValueError('이미지는 10MB 이하로 선택해 주세요.')
                with open(path, 'rb') as image:
                    response = requests.post(API_BASE_URL + '/api/ocr',
                        headers={'Authorization': 'Bearer ' + token},
                        files={'image': ('receipt.jpg', image)}, timeout=75)
                data = response.json()
                if not response.ok:
                    raise RuntimeError(data.get('error', 'OCR 서버 오류'))
                Clock.schedule_once(lambda _dt, value=data: completed(data=value), 0)
            except Exception as exc:
                Clock.schedule_once(lambda _dt, msg=str(exc): completed(error=msg), 0)
        threading.Thread(target=worker, daemon=True).start()

    def review_receipt(self, data, index=None):
        layout = BoxLayout(orientation='vertical', padding=dp(10), spacing=dp(8))
        layout.add_widget(make_label('품목명 | 수량 | 품목 합계 금액 (단가 아님)\n한 줄에 한 품목. 할인은 품목 금액에 반영하세요.', 13,
                                    size_hint_y=None, height=dp(50)))
        editor = make_text_input(text='\n'.join(f"{x['item']} | {x['qty']} | {x['price']}" for x in data.get('items', [])), multiline=True)
        total = make_text_input(text=str(data.get('total', 0)), hint_text='영수증 총액', multiline=False, size_hint_y=None, height=dp(44))
        layout.add_widget(editor)
        layout.add_widget(total)
        actions = BoxLayout(size_hint_y=None, height=dp(44), spacing=dp(8))
        save, cancel = make_primary_button('확인 후 저장'), make_button('취소')
        actions.add_widget(save); actions.add_widget(cancel); layout.add_widget(actions)
        popup = Popup(title='영수증 인식 결과 수정', title_font=FONT_BOLD, content=layout, size_hint=(.96,.9))
        def commit(*_):
            try:
                items=[]
                for line in editor.text.splitlines():
                    if not line.strip(): continue
                    name, qty, price = [x.strip() for x in line.rsplit('|',2)]
                    qty, price = int(qty), int(price.replace(',',''))
                    if not name or len(name)>150 or not 1<=qty<=10000 or not 0<=price<=1_000_000_000:
                        raise ValueError('품목명/수량/금액을 확인하세요.')
                    items.append(dict(item=name,qty=qty,price=price))
                amount=int(total.text.replace(',',''))
                if not items or not 0<amount<=1_000_000_000 or sum(x['price'] for x in items)!=amount:
                    raise ValueError('품목 합계와 영수증 총액이 같아야 합니다.')
                receipt={'items':items,'total':amount}
                if index is None: SESSION_STATE['receipts'].append(receipt)
                else: SESSION_STATE['receipts'][index]=receipt
                popup.dismiss(); self.build_ui()
            except (ValueError, IndexError) as exc:
                show_message('입력 확인', str(exc))
        save.bind(on_press=commit); cancel.bind(on_press=lambda *_: popup.dismiss())
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
    def __init__(self, member, max_qty, on_changed, **kwargs):
        super().__init__(orientation="horizontal", size_hint_y=None,
                         height=dp(44), spacing=dp(7), **kwargs)
        self.member = member
        self.max_qty = int(max_qty)
        self.on_changed = on_changed
        self._updating = False

        self.checkbox = CheckBox(size_hint_x=None, width=dp(30))
        self.checkbox.bind(active=self._check_changed)
        self.add_widget(self.checkbox)

        self.name_label = make_label(member, size_hint_x=0.58, halign="left", valign="middle")
        self.name_label.bind(size=self.name_label.setter("text_size"))
        self.add_widget(self.name_label)

        self.qty = make_text_input(
            text="1", multiline=False, input_filter="int",
            size_hint_x=0.25, size_hint_y=None, height=dp(38)
        )
        self.qty.disabled = True
        self.qty.bind(text=self._qty_changed)
        self.add_widget(self.qty)

    def _check_changed(self, *_):
        self.qty.disabled = not self.checkbox.active
        if self.checkbox.active and not self.qty.text:
            self.qty.text = "1"
        self.on_changed()

    def _qty_changed(self, *_):
        if not self._updating:
            self.on_changed()

    def selected_qty(self):
        if not self.checkbox.active:
            return 0
        try:
            q = int(self.qty.text)
        except Exception:
            q = 1
        return max(1, min(q, self.max_qty))

    def set_max_allowed(self, allowed):
        allowed = max(1, int(allowed))
        if self.checkbox.active:
            try:
                current = int(self.qty.text)
            except Exception:
                current = 1
            if current > allowed:
                self._updating = True
                self.qty.text = str(allowed)
                self._updating = False

    def set_check_disabled(self, disabled):
        self.checkbox.disabled = bool(disabled and not self.checkbox.active)


class SettleScreen(Screen):
    def on_leave(self):
        if not self.current_receipts or not hasattr(self, 'bank_input'):
            return
        SESSION_STATE['draft'] = {
            'request_id': self._request_id,
            'bank': self.bank_input.text, 'account': self.acc_input.text,
            'names': [x.text for x in self.name_inputs],
            'receipts': copy.deepcopy(self.current_receipts),
            'applied': getattr(self, '_applied_members', []),
            'rows': {key: [(r.member, r.selected_qty()) for r in rows] for key,rows in self.member_rows.items()}
        }

    def on_enter(self):
        self._submitting = False
        self._request_id = SESSION_STATE.get("draft", {}).get("request_id", uuid.uuid4().hex)
        self.build_ui()
        draft = SESSION_STATE.get('draft', {})
        if not draft or not self.current_receipts:
            return
        self.bank_input.text = draft['bank']; self.acc_input.text = draft['account']
        names = draft['names']
        if names:
            self.name_inputs[0].text = names[0]
            for name in names[1:]: self.add_member_field(name)
        if draft.get('applied') == self.collect_members():
            self.render_menu_items()
            for key, saved in draft.get('rows', {}).items():
                ri, ii = key
                old = draft.get('receipts', [])
                if ri >= len(old) or ri >= len(self.current_receipts) or old[ri] != self.current_receipts[ri]:
                    continue
                for row, (name, qty) in zip(self.member_rows.get(key, []), saved):
                    if row.member == name and qty:
                        row.checkbox.active = True; row.qty.text = str(qty)
            self.recalculate_limits()

    def build_ui(self):
        self.clear_widgets()
        self.name_inputs = []
        self.member_rows = {}
        self.current_receipts = copy.deepcopy(SESSION_STATE.get("receipts", []))

        main = add_page_layout()
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
            self.add_widget(main)
            return

        main.add_widget(make_label("입금받을 계좌 정보", 17, True, size_hint_y=None, height=dp(34)))

        account_row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(45), spacing=dp(8))
        self.bank_input = Spinner(
            text="토스뱅크",
            values=("토스뱅크", "카카오뱅크", "국민은행", "신한은행", "우리은행", "하나은행", "농협은행", "기업은행"),
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
        friend_scroll = ScrollView(size_hint_y=None, height=dp(44), do_scroll_y=False)
        self.friend_quick_box.size_hint_x = None
        self.friend_quick_box.bind(minimum_width=self.friend_quick_box.setter("width"))
        friend_scroll.add_widget(self.friend_quick_box)
        main.add_widget(friend_scroll)
        self.render_friend_quick_add()

        total = sum(r["total"] for r in self.current_receipts)
        total_card = Card(size_hint_y=None, height=dp(66))
        total_card.add_widget(make_label(f"전체 영수증 {len(self.current_receipts)}개", 13, False,
                                         color=COLOR_MUTED, size_hint_y=None, height=dp(22)))
        total_card.add_widget(make_label(f"총 {total:,}원", 20, True, size_hint_y=None, height=dp(30)))
        main.add_widget(total_card)

        self.items_scroll = ScrollView()
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
        settle_btn.bind(on_press=lambda *_: self.process_settlement())
        action_row.add_widget(add_receipt)
        action_row.add_widget(settle_btn)
        main.add_widget(action_row)

        self.add_widget(main)

    def apply_members(self, *_):
        for inp in self.name_inputs:
            inp.focus = False

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

        minus = make_button("−", bold=True, size_hint_x=None, width=dp(42))
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

        for friend in friends:
            label = f"{friend['name']} ({friend['email']})"
            btn = make_button(label, size_hint_x=None, width=dp(180))
            btn.bind(on_press=lambda _btn, name=label: self.fill_next_member(name))
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
        self._applied_members = members[:]
        self.items_container.clear_widgets()
        self.member_rows = {}

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
                height=dp(70 + sum(78 + 50 * len(members) for _ in items))
            )
            receipt_card.add_widget(make_label(
                f"영수증 {receipt_index + 1} · {receipt['total']:,}원",
                16, True, size_hint_y=None, height=dp(28)
            ))

            for item_index, item in enumerate(items):
                max_qty = max(1, int(item["qty"]))
                sub = Card(size_hint_y=None, height=dp(72 + 50 * len(members)))
                sub.add_widget(make_label(
                    f"{item['item']}  {item['price']:,}원 · {max_qty}개",
                    14, True, size_hint_y=None, height=dp(26)
                ))

                rows = []
                for member in members:
                    row = MemberRow(member, max_qty, self.recalculate_limits)
                    rows.append(row)
                    sub.add_widget(row)

                key = (receipt_index, item_index)
                self.member_rows[key] = rows
                receipt_card.add_widget(sub)

            self.items_container.add_widget(receipt_card)

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

            for row in rows:
                own = row.selected_qty()
                other = selected - own
                remaining = max_qty - other
                if row.checkbox.active:
                    row.set_max_allowed(max(1, remaining))
                    row.set_check_disabled(False)
                else:
                    row.set_check_disabled(remaining <= 0)

    def process_settlement(self):
        if getattr(self, '_submitting', False): return
        members = self.collect_members()
        names = [x.text.strip() for x in self.name_inputs if x.text.strip()]
        if len(names) != len(set(names)):
            show_message('동명이인', '표시 이름에 구분자를 붙이거나 이메일이 포함된 친구 버튼으로 추가하세요.')
            return
        if members != getattr(self, '_applied_members', []):
            show_message('참여자 변경', '참여자 적용을 다시 누르고 배분을 확인하세요.')
            return
        if any(sum(i['price'] for i in r['items']) != r['total'] for r in self.current_receipts):
            show_message('총액 불일치', '영수증 수정 화면에서 품목 합계와 총액을 맞춰 주세요.')
            return
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

        member_totals = {m: 0 for m in members}
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

            # Largest remainder method: deterministic integer KRW allocation.
            bases = {name: price * qty // total_selected for name,qty in shares.items()}
            remainder = price - sum(bases.values())
            order = sorted(shares, key=lambda name: -(price * shares[name] % total_selected))
            for name in order[:remainder]: bases[name] += 1
            for name, amount in bases.items(): member_totals[name] += amount

        final_totals = member_totals
        friend_map = {f"{f['name']} ({f['email']})": f['id'] for f in SESSION_STATE.get('friends', [])}
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

        self._submitting = True
        async_api(
            "POST", "/api/settlements",
            {
                "request_id": self._request_id,
                "bank": bank,
                "account": account,
                "participants": participants,
                "receipts": receipts_payload,
            },
            self.settlement_created,
            self.settlement_failed,
        )

    def settlement_failed(self, error):
        self._submitting = False
        show_message('정산 생성 실패', error)

    def settlement_created(self, data):
        self._submitting = False
        share_url = data["share_url"]
        copied = True
        try:
            Clipboard.copy(share_url)
        except Exception:
            copied = False
            show_message('복사 실패: 정산은 저장됨', share_url)

        total = data["total_amount"]
        SESSION_STATE["history"].insert(0, {
            "date": datetime.date.today().strftime("%Y-%m-%d"),
            "total": total,
            "members": [p["name"] for p in data["participants"]],
            "count": len(data["receipts"]),
        })

        # 결과 팝업 없이 링크를 바로 클립보드에 복사
        if copied: show_toast(f"정산 링크가 복사되었습니다.\n{total:,}원")
        SESSION_STATE["receipts"] = []
        self.current_receipts = []
        SESSION_STATE["draft"] = {}
        self.manager.current = "home"
        load_history_from_server()


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
            (n for n in data if n["id"] not in old_ids and not n.get("read") and n["kind"] == "payment_received"),
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
        if root.current == "home": root.get_screen("home").on_enter()

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
        return sm

    def on_start(self):
        self._notification_event = None
        if platform == 'android':
            try:
                from android.permissions import request_permissions
                from jnius import autoclass
                if autoclass('android.os.Build$VERSION').SDK_INT >= 33:
                    request_permissions(['android.permission.POST_NOTIFICATIONS'])
            except Exception:
                pass
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
