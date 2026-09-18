# -*- coding: utf-8 -*-
"""和弦张力等级查询工具 —— 手机界面版（Kivy）

电脑上预览：在仓库根目录执行  python mobile/main.py
打包安卓 APK：见 mobile/README.md

本文件不改动命令行程序 src/chord_calculate.py：只 import 它、复用其中全部
计算与查询函数（query_single / search_static / search_dynamic /
run_attr_search_cond / run_attr_search_static / run_generate 等），
输出用 redirect_stdout 原样接住显示 —— 与桌面版 src/chord_ui.py 同一套做法，
算法/数据/文案只有一份。

五个页签与桌面版一致：
  查询 —— 单和弦 / 和声进行（也可写 含音/音数约束、写 生成/查/batch/等级名 跳页）
  等级 —— 温度 11 档查找（静态 / 动态 / 两个都查；随机一个 / 全部输出），可加含音/音数约束
  批量 —— 每行一个和弦
  查   —— 和弦查属性；属性查和弦（静态 / 动态[温度/张力/温度差/张力差 四条件可混填]），可加含音/音数约束
  生成 —— 起点和弦 + 条件（动态温度/动态张力/温度差/张力差 + 下一个和弦的静态温度/静态张力）+ 含音/音数约束 → 下一个和弦

含音/音数约束写法：含 C E、4音、3-4音（约束加在“找出来的和弦”上）。
结果区（DragScrollTextInput）只读、可以用手指直接上下拖动翻看长结果
（安卓上 readonly 的 TextInput 不可聚焦，Kivy 自带的滑动滚动用不了，见类注释）。

查询在后台线程里跑，结果经 Clock 回主线程显示，界面不会卡死。
"""
import contextlib
import io
import os
import sys
import threading
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import chord_calculate as cc

from kivy.config import Config
from kivy.utils import platform

IS_ANDROID = (platform == "android")
if not IS_ANDROID:
    Config.set("graphics", "width", "420")
    Config.set("graphics", "height", "820")

from kivy.app import App
from kivy.clock import Clock
from kivy.core.text import LabelBase
from kivy.core.window import Window
from kivy.metrics import dp, sp
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.label import Label
from kivy.uix.spinner import Spinner, SpinnerOption
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

# 结果区/输入框统一字体；中文字形在安卓上必须显式指定，否则是方框
FONT = "CJK"


class CjkSpinnerOption(SpinnerOption):
    """下拉选项要单独指定中文字体：Kivy 只把字体设在 Spinner 按钮上，
    弹出的选项用小部件默认字体，安卓上全是方框（2026-09-16 手机实测）。"""

    def __init__(self, **kwargs):
        kwargs.setdefault("font_name", FONT)
        super().__init__(**kwargs)


def _setup_font():
    """找一个带中文字形的字体注册给 Kivy。优先随包字体，找不到再扫安卓系统字体。"""
    here = os.path.dirname(os.path.abspath(__file__))
    candidates = [
        # 随包字体（本仓库放了 Noto Sans SC，开源可随包；有它在就不会出方框）
        os.path.join(here, "assets", "cjk.otf"),
        os.path.join(here, "assets", "cjk.ttf"),
        os.path.join(here, "assets", "cjk.ttc"),
        "/system/fonts/NotoSansCJK-Regular.ttc",          # AOSP 标准
        "/system/fonts/NotoSansSC-Regular.otf",
        "/system/fonts/NotoSansSC-Regular.ttf",
        "/system/fonts/DroidSansFallback.ttf",            # 老设备
        "/system/fonts/MiSans-Regular.ttf",               # 小米
        "/system/fonts/OPPOSans-Regular.ttf",             # OPPO
        "/system/fonts/HarmonyOS_Sans_SC_Regular.ttf",    # 华为
        r"C:\Windows\Fonts\msyh.ttc",                     # 电脑上预览用
        r"C:\Windows\Fonts\msyh.ttf",
        r"C:\Windows\Fonts\simhei.ttf",
    ]
    if os.path.isdir("/system/fonts"):
        for name in sorted(os.listdir("/system/fonts")):
            low = name.lower()
            if ("cjk" in low or "fallback" in low or "misans" in low) and low.endswith((".ttf", ".ttc", ".otf")):
                candidates.append(os.path.join("/system/fonts", name))
    for path in candidates:
        if path and os.path.exists(path):
            try:
                LabelBase.register(name=FONT, fn_regular=path)
                return path
            except Exception:
                continue
    return None


_FONT_PATH = _setup_font()


# ========== 查询核心（与桌面版 src/chord_ui.py 同一套胶水，界面按钮与自测脚本共用） ==========
def _capture(fn, *args):
    """把查询函数的 stdout 原样接住，返回字符串。"""
    buf = io.StringIO()
    with contextlib.redirect_stdout(buf):
        fn(*args)
    return buf.getvalue()


def core_single(text):
    """单和弦 / 和声进行（“查 → 和弦查属性”也走这里）。"""
    return _capture(cc.query_single, text)


def _parse_con_text(con_text):
    """界面约束框文本 → (con, 错误消息)。空 = (None, "")。"""
    con, err = cc.parse_constraint_arg(con_text or "")
    return con, (err or "")


def core_grade(name, kinds, mode, con_text=""):
    """等级查找。kinds 是 ("静态",) / ("动态",) / ("静态", "动态")；mode 是 "one" / "all"。
    con_text 非空 = 含音/音数约束（结果和弦自身必须满足）。"""
    grade = cc.resolve_grade(name)
    con, cerr = _parse_con_text(con_text)
    if cerr:
        return cerr + "\n"
    out = ["", f"温度等级查找：{grade}", "-" * 60]
    if "静态" in kinds:
        out.append(_capture(cc.search_static, grade, mode, con).rstrip("\n"))
    if "动态" in kinds:
        out.append(_capture(cc.search_dynamic, grade, mode, con).rstrip("\n"))
    return "\n".join(out) + "\n"


def core_batch(text_lines):
    """批量查询：每行一个和弦（支持 / 进行），与命令行 batch 同一条打印路径。"""
    out = ["", "=" * 60, "批量查询结果", "=" * 60]
    for line in text_lines:
        line = line.strip()
        if not line:
            continue
        if "/" in line or "／" in line:
            out.append(f"\n输入：{line}")
            out.append(_capture(cc.query_progression, line).rstrip("\n"))
            continue
        pitch_classes, names, errors = cc.parse_input(line)
        if errors:
            out.append(f"\n输入：{line}")
            out.append(f"  警告：无法识别的音名 {errors}")
            continue
        if len(pitch_classes) < 2:
            out.append(f"\n输入：{line}")
            out.append("  至少需要两个不同的音。")
            continue
        level, span, (major2, semitone), (max_run, run_count) = cc.get_tension_level(pitch_classes)
        out.append(f"\n输入：{line}")
        out.append(cc.format_result(names, pitch_classes, level, span, major2, semitone, max_run, run_count))
    return "\n".join(out) + "\n"


def core_attr_static(t_text, x_text, mode, con_text=""):
    """属性查和弦（静态）：温度条件 × 张力条件，至少输一个；可加含音/音数约束。
    解析、查错、分发与命令行走同一条路（cc.run_attr_search_static），提示一字不差。"""
    con, cerr = _parse_con_text(con_text)
    if cerr:
        return cerr + "\n"
    return _capture(cc.run_attr_search_static, t_text, x_text, mode, con)


def core_attr_dynamic(t_text, x_text, td_text, xd_text, mode, con_text=""):
    """属性查和弦（动态）：温度/张力/温度差/张力差四条件可混填，至少一个；可加含音/音数约束。
    解析、查错、分发与命令行走同一条路（cc.run_attr_search_cond），提示一字不差。"""
    con, cerr = _parse_con_text(con_text)
    if cerr:
        return cerr + "\n"
    return _capture(cc.run_attr_search_cond, t_text, x_text, td_text, xd_text, mode, con)


def core_generate(start_text, t_text, x_text, td_text, xd_text, st_text, sx_text, mode, con_text=""):
    """生成下一个和弦：起点和弦 + 六行条件/约束，至少填一个。
    解析、查错、分发与命令行走同一条路（cc.run_generate），提示一字不差。"""
    con, cerr = _parse_con_text(con_text)
    if cerr:
        return cerr + "\n"
    return _capture(cc.run_generate, start_text, t_text, x_text, td_text, xd_text, st_text, sx_text, mode, con)


def _prewarm_caches():
    """开屏后台先把几张索引表建好（纯枚举/解码、不抽随机数，谁的输出都不变）。
    不预热的话，第一次点「等级」或「查」要现场枚举多等半秒（手机更久）。
    表名哪天改了就当没有，静默跳过。"""
    for name in ("_static_rows", "_dyn_data", "_pair4_totals", "_diff_static_values"):
        fn = getattr(cc, name, None)
        if fn is None:
            continue
        try:
            fn()
        except Exception:
            pass


# ========== 界面小零件 ==========
# 页签内容区是 Kivy 默认主题的深灰底（约 RGB 48），这几处文字固定用浅色，否则看不清
def hint_label(text, app):
    """灰色小字提示，随宽度自动换行、自动加高。"""
    lbl = Label(text=text, font_name=FONT, font_size=sp(12), color=(0.64, 0.64, 0.68, 1),
                halign="left", valign="top", size_hint_y=None, height=dp(1))
    lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
    lbl.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
    return lbl


def title_label(text, app):
    lbl = Label(text=text, font_name=FONT, font_size=sp(13), color=(0.9, 0.9, 0.94, 1),
                halign="left", valign="top", size_hint_y=None, height=dp(1))
    lbl.bind(width=lambda w, v: setattr(w, "text_size", (v, None)))
    lbl.bind(texture_size=lambda w, v: setattr(w, "height", v[1]))
    return lbl


class DragScrollTextInput(TextInput):
    """结果区：只读 + 手指按住直接上下拖动翻看。

    安卓上 readonly 的 TextInput 不可聚焦（Kivy 处理 readonly 时把 is_focusable 关了），
    而 Kivy 自带的滑动滚动（scroll_from_swipe）要求先有焦点；更糟的是
    TextInput.on_touch_move 一看没焦点就 ungrab —— 拖一下就断。两条叠起来，
    手机上结果区就拖不动（2026-09-18 手机实感 + 模拟触摸定位）。
    这里自己跟手：按下记位置，拖动时按位移改 scroll_y（与 Kivy 自带手势同向、
    同样夹在 0 ~ 可滚范围），拖动期间不再把事件递给 TextInput 的原逻辑，
    免得它把 grab 丢掉；滚轮、双击、长按等还是 Kivy 的原样。
    """

    _drag_last_y = None

    def on_touch_down(self, touch):
        handled = super().on_touch_down(touch)
        if handled and self.multiline and self.minimum_height > self.height:
            self._drag_last_y = touch.y
        else:
            self._drag_last_y = None
        return handled

    def on_touch_move(self, touch):
        if self._drag_last_y is not None and touch.grab_current is self:
            dy = touch.y - self._drag_last_y
            self._drag_last_y = touch.y
            if dy:
                max_scroll_y = max(0, self.minimum_height - self.height)
                self.scroll_y = min(max(0, self.scroll_y + dy), max_scroll_y)
                self._trigger_update_graphics()
                self._have_scrolled = True
                self.cancel_long_touch_event()
            return True
        return super().on_touch_move(touch)

    def on_touch_up(self, touch):
        self._drag_last_y = None
        return super().on_touch_up(touch)


def result_box():
    """只读结果区：可拖动滚动、可选中复制，但改不了。"""
    ti = DragScrollTextInput(text="", readonly=True, multiline=True, font_name=FONT, font_size=sp(13),
                             size_hint_y=1)
    return ti


def entry(hint=""):
    return TextInput(text="", hint_text=hint, multiline=False, font_name=FONT,
                     font_size=sp(14), size_hint_y=None, height=dp(40),
                     padding=[dp(6), dp(8)])


def flat_button(text, on_press):
    return Button(text=text, font_name=FONT, font_size=sp(14),
                  size_hint_y=None, height=dp(40), on_press=on_press)


def toggle_row(options, group, initial):
    """一行互斥按钮，返回 (外框, {文字: 按钮})。"""
    row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(38), spacing=dp(4))
    buttons = {}
    for opt in options:
        btn = ToggleButton(text=opt, font_name=FONT, font_size=sp(13), group=group,
                           state="down" if opt == initial else "normal")
        buttons[opt] = btn
        row.add_widget(btn)
    return row, buttons


def picked(buttons):
    for text, btn in buttons.items():
        if btn.state == "down":
            return text
    return None


def set_visible(widget, flag, height=None):
    """显示/隐藏一行控件（隐藏时高度压到 0、不占位、点不到）。"""
    if flag:
        widget.disabled = False
        widget.opacity = 1
        if height is not None:
            widget.height = height
            widget.size_hint_y = None
    else:
        widget.disabled = True
        widget.opacity = 0
        widget.size_hint_y = None
        widget.height = 0


class ChordTabbedPanel(TabbedPanel):
    """开屏那一枪不能留：do_default_tab=False 时 Kivy 在 __init__ 里排了个
    Clock.schedule_once(_switch_to_first_tab)，实测它要到开屏后 1.1 秒左右才响
    （首帧就要 0.97 秒，头几帧都在载字体和纹理）。这一枪会把这段时间里已经切走的
    页签弹回「查询」——手快点页签的、或「查询」页输「生成 …」跳页的，都会被弹回。
    这里直接把它掐掉，首个页签由 build() 自己 switch_to，时序完全确定。"""

    def _switch_to_first_tab(self, *l):
        pass


# ========== 主界面 ==========
class ChordApp(App):
    title = "和弦张力等级查询工具"

    def build(self):
        # 默认 5ms 的时间片太长：后台线程算查询时（动态“全部输出”每次要算 2 秒左右），
        # 主线程抢 GIL 会连续错过好几帧 —— 2026-09-16 实测计算期间主循环卡帧
        # p99 28.9ms、反复出现 29ms 顿挫；缩到 1ms 后 p99 降到 15.4ms、最长 21ms。
        sys.setswitchinterval(0.001)
        self._pending = 0
        self._result_target = None
        self._tick_ev = None

        root = BoxLayout(orientation="vertical")
        self.status = Label(text="就绪", font_name=FONT, font_size=sp(12),
                            size_hint_y=None, height=dp(26),
                            color=(0.9, 0.9, 0.94, 1), halign="left", valign="middle")
        self.status.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - dp(12), v[1])))
        self.status.padding = [dp(6), 0, dp(6), 0]

        self.tp = ChordTabbedPanel(do_default_tab=False, tab_pos="top_mid", tab_height=dp(36))
        # 五个页签平分一屏宽：TabbedPanel 默认每签 100dp，5×100 会把「生成」挤出屏幕
        self.tp.tab_width = Window.width / 5
        Window.bind(width=lambda _w, v: setattr(self.tp, "tab_width", v / 5))
        self.tab_query_item = TabbedPanelItem(text=" 查询 ", font_name=FONT)
        self.tab_grade_item = TabbedPanelItem(text=" 等级 ", font_name=FONT)
        self.tab_batch_item = TabbedPanelItem(text=" 批量 ", font_name=FONT)
        self.tab_attr_item = TabbedPanelItem(text=" 查 ", font_name=FONT)
        self.tab_gen_item = TabbedPanelItem(text=" 生成 ", font_name=FONT)
        for item in (self.tab_query_item, self.tab_grade_item,
                     self.tab_batch_item, self.tab_attr_item, self.tab_gen_item):
            self.tp.add_widget(item)

        self._build_tab_query()
        self._build_tab_grade()
        self._build_tab_batch()
        self._build_tab_attr()
        self._build_tab_gen()
        self.tp.switch_to(self.tab_query_item)   # 默认停在「查询」页（取代 Kivy 那枪迟到的首签切换）

        root.add_widget(self.tp)
        root.add_widget(self.status)
        return root

    def on_start(self):
        if IS_ANDROID:
            try:
                Window.softinput_mode = "below_target"
            except Exception:
                pass
        threading.Thread(target=_prewarm_caches, daemon=True).start()

    # ---------- 查询调度 ----------
    def _start_job(self, work, target):
        """后台线程跑查询；同一时刻只允许一个，跑完经 Clock 回主线程显示。"""
        if self._pending:
            self.status.text = "上一个查询还在跑，稍等…"
            return
        self._pending += 1
        self._result_target = target
        t0 = time.perf_counter()
        self._tick_ev = Clock.schedule_interval(lambda _dt: self._show_elapsed(t0), 0.5)
        self._show_elapsed(t0)

        def runner():
            try:
                content = work()
            except Exception as exc:  # 保底：出错也只显示在结果区，不让程序崩
                content = f"  出错了：{exc}\n"
            dt = time.perf_counter() - t0
            Clock.schedule_once(lambda _dt: self._finish(content, dt), 0)

        threading.Thread(target=runner, daemon=True).start()

    def _show_elapsed(self, t0):
        """长查询要算好几秒，状态栏把秒数跳起来，别让人以为程序死了。"""
        self.status.text = f"查询中… 已用 {time.perf_counter() - t0:.1f} 秒"

    def _finish(self, content, dt):
        self._pending -= 1
        if self._tick_ev is not None:
            self._tick_ev.cancel()
            self._tick_ev = None
        self.status.text = f"完成（{dt:.2f} 秒）"
        target = self._result_target
        target.text = content.rstrip("\n")
        target.scroll_y = 1
        target.cursor = (0, 0)

    # ---------- 页签 1：查询 ----------
    def _build_tab_query(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        box.add_widget(title_label("输入和弦音（空格或逗号分隔，如 C E G）；和声进行用 / 隔开（如 C E G / D F A）", self))
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.ent_query = entry()
        self.ent_query.bind(on_text_validate=lambda *_: self._run_query())
        row.add_widget(self.ent_query)
        row.add_widget(flat_button("查询", lambda *_: self._run_query()))
        row.add_widget(flat_button("清空", lambda *_: self._clear(self.ent_query, self.box_query)))
        box.add_widget(row)
        box.add_widget(hint_label(
            "降号用 jD 或 bD（Db、Eb、Ab、Bb）；升号用 #F；带八度也可以（八度会被忽略）。"
            "输 等级名（如 巨暖）会跳到「等级」页；输 查 / batch / 生成 会跳到对应页；"
            "还可加含音/音数约束（如 大暖 含 C、生成 C E G 3-4音）。", self))
        self.box_query = result_box()
        box.add_widget(self.box_query)
        self.tab_query_item.add_widget(box)

    def _run_query(self):
        text = self.ent_query.text.strip()
        if not text:
            self.status.text = "请先输入和弦"
            return
        # 与命令行同一套路由：先剥出 含音/音数约束，剩下的照旧
        rest, con, cdesc, cerr = cc.parse_constraints(text)
        if cerr:
            self.status.text = cerr
            return
        con_text = cc.constraint_desc(con) if con is not None else ""
        if rest.lower() == "batch":
            if con is not None:
                self.status.text = "批量查询不支持含音/音数约束（每行都是给定的和弦）"
                return
            self.tp.switch_to(self.tab_batch_item)
            self.status.text = "已跳到「批量」页"
            return
        if rest.startswith("生成"):
            self.tp.switch_to(self.tab_gen_item)
            self.ent_gen_start.text = rest[2:].strip()
            self.ent_gen_con.text = con_text
            self.status.text = "已跳到「生成」页，起点和弦与约束已填好，补条件后点「生成」"
            return
        if rest in ("查", "查询"):
            self.tp.switch_to(self.tab_attr_item)
            # 程序改 state 不会触发 ToggleButton 的互斥逻辑，另一颗要手动弹起
            self.attr_dir_btns["属性查和弦"].state = "down"
            self.attr_dir_btns["和弦查属性"].state = "normal"
            self._refresh_attr()
            self.ent_as_con.text = con_text
            self.status.text = "已跳到「查」页（方向：属性查和弦），约束已填好"
            return
        if not rest:
            self.status.text = f"只写了约束（{cdesc}）：可输 等级名 / 查 / 生成 开头，如 大暖 含 C、生成 C E G 含 C E"
            return
        grade = cc.resolve_grade(rest)
        if grade:
            self.tp.switch_to(self.tab_grade_item)
            self.grade_spin.text = grade
            self.ent_grade_con.text = con_text
            self.status.text = f"“{rest}”是温度等级名，已跳到「等级」页，点「查询」即可"
            return
        if con is not None:
            self.status.text = f"含音/音数约束（{cdesc}）是“找和弦”用的，跟在 等级名 / 查 / 生成 后面；单个和弦查属性不用约束"
            return
        self._start_job(lambda: core_single(rest), self.box_query)

    # ---------- 页签 2：等级查找 ----------
    def _build_tab_grade(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(Label(text="温度等级：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(76)))
        self.grade_spin = Spinner(text="巨暖", values=cc.TEMP_GRADES, font_name=FONT,
                                  font_size=sp(13), size_hint_y=None, height=dp(40),
                                  option_cls=CjkSpinnerOption)
        row.add_widget(self.grade_spin)
        box.add_widget(row)

        row2, self.grade_kind_btns = toggle_row(["静态", "动态", "两个都查"], "grade_kind", "静态")
        box.add_widget(Label(text="查哪种：", font_name=FONT, font_size=sp(13), size_hint_y=None, height=dp(20)))
        box.add_widget(row2)

        row3, self.grade_mode_btns = toggle_row(["随机一个", "全部输出"], "grade_mode", "随机一个")
        box.add_widget(Label(text="输出：", font_name=FONT, font_size=sp(13), size_hint_y=None, height=dp(20)))
        box.add_widget(row3)

        row4 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row4.add_widget(Label(text="约束：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        self.ent_grade_con = entry(hint="含 C E、4音、3-4音，可留空")
        self.ent_grade_con.bind(on_text_validate=lambda *_: self._run_grade())
        row4.add_widget(self.ent_grade_con)
        box.add_widget(row4)

        box.add_widget(flat_button("查询", lambda *_: self._run_grade()))
        box.add_widget(hint_label(
            "每档 2 度：巨冷 大冷 中冷 小冷 微冷 平衡（中性） 微暖 小暖 中暖 大暖 巨暖；"
            "零值（平衡/中性 两种标签）合并进中间档。动态“全部输出”＝总数 + 20 条随机示例。"
            "约束加在“找出来的和弦”上（结果和弦必须满足）。", self))
        self.box_grade = result_box()
        box.add_widget(self.box_grade)
        self.tab_grade_item.add_widget(box)

    def _run_grade(self):
        grade = self.grade_spin.text
        if not cc.resolve_grade(grade):
            self.status.text = "请先选一个等级"
            return
        kind = picked(self.grade_kind_btns)
        kinds = ("静态", "动态") if kind == "两个都查" else (kind,)
        mode = "all" if picked(self.grade_mode_btns) == "全部输出" else "one"
        con_text = self.ent_grade_con.text
        self._start_job(lambda: core_grade(grade, kinds, mode, con_text), self.box_grade)

    # ---------- 页签 3：批量 ----------
    def _build_tab_batch(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        box.add_widget(title_label("每行一个和弦（支持 / 进行），空行会被忽略：", self))
        self.txt_batch_in = TextInput(text="", multiline=True, font_name=FONT, font_size=sp(14),
                                      size_hint_y=None, height=dp(110))
        box.add_widget(self.txt_batch_in)
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(flat_button("查询", lambda *_: self._run_batch()))
        row.add_widget(flat_button("清空", lambda *_: self._clear(self.txt_batch_in, self.box_batch)))
        row.add_widget(BoxLayout())  # 占位，把按钮推到左边
        box.add_widget(row)
        self.box_batch = result_box()
        box.add_widget(self.box_batch)
        self.tab_batch_item.add_widget(box)

    def _run_batch(self):
        lines = [l.strip() for l in self.txt_batch_in.text.splitlines()]
        lines = [l for l in lines if l]
        if not lines:
            self.status.text = "请先输入内容"
            return
        self._start_job(lambda: core_batch(lines), self.box_batch)

    # ---------- 页签 4：查 ----------
    def _build_tab_attr(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        row_dir, self.attr_dir_btns = toggle_row(["和弦查属性", "属性查和弦"], "attr_dir", "和弦查属性")
        box.add_widget(row_dir)

        # 方向一：和弦查属性
        self.ca_box = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None, height=dp(1))
        row_ca, self.ca_kind_btns = toggle_row(["静态（1 个和弦）", "动态（2 个和弦，用 / 隔开）"], "ca_kind", "静态（1 个和弦）")
        self.ca_box.add_widget(row_ca)
        row_ca2 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.ent_ca = entry()
        self.ent_ca.bind(on_text_validate=lambda *_: self._run_attr())
        row_ca2.add_widget(self.ent_ca)
        row_ca2.add_widget(flat_button("查询", lambda *_: self._run_attr()))
        self.ca_box.add_widget(row_ca2)
        self.lbl_ca_hint = hint_label("请输入一个和弦，如 C E G", self)
        self.ca_box.add_widget(self.lbl_ca_hint)
        self.ca_box.height = dp(38 + 40 + 6 + 22)
        box.add_widget(self.ca_box)

        # 方向二：属性查和弦（静态 / 动态[温度/张力/温度差/张力差 四条件可混填]）
        self.as_box = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None, height=dp(1))
        row_as, self.as_kind_btns = toggle_row(["静态", "动态"], "as_kind", "静态")
        self.as_box.add_widget(row_as)

        def cond_row(label_text):
            row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
            lbl = Label(text=label_text, font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(150))
            ent = entry()
            ent.bind(on_text_validate=lambda *_: self._run_attr())
            row.add_widget(lbl)
            row.add_widget(ent)
            return row, lbl, ent

        self.row_c1, self.lbl_c1, self.ent_c1 = cond_row("温度条件：")
        self.as_box.add_widget(self.row_c1)
        self.row_c2, self.lbl_c2, self.ent_c2 = cond_row("张力条件：")
        self.as_box.add_widget(self.row_c2)
        self.row_c3, self.lbl_c3, self.ent_c3 = cond_row("温度差条件（1~20）：")
        self.as_box.add_widget(self.row_c3)
        self.row_c4, self.lbl_c4, self.ent_c4 = cond_row("张力差条件（1~10）：")
        self.as_box.add_widget(self.row_c4)
        self.lbl_as_hint = hint_label("", self)
        self.as_box.add_widget(self.lbl_as_hint)

        row_as_con = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row_as_con.add_widget(Label(text="约束：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        self.ent_as_con = entry(hint="含 C E、4音、3-4音，可留空")
        self.ent_as_con.bind(on_text_validate=lambda *_: self._run_attr())
        row_as_con.add_widget(self.ent_as_con)
        self.as_box.add_widget(row_as_con)

        row_mode = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(4))
        row_mode.add_widget(Label(text="输出：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        mode_box, self.as_mode_btns = toggle_row(["随机一个", "全部输出"], "as_mode", "随机一个")
        mode_box.size_hint_x = 1
        row_mode.add_widget(mode_box)
        row_mode.add_widget(flat_button("查询", lambda *_: self._run_attr()))
        self.as_box.add_widget(row_mode)
        self.as_box.height = dp(410)
        box.add_widget(self.as_box)

        self.box_attr = result_box()
        box.add_widget(self.box_attr)
        self.tab_attr_item.add_widget(box)

        for btn in self.attr_dir_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())
        for btn in self.as_kind_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())
        for btn in self.ca_kind_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())

        self._refresh_attr()

    def _refresh_attr(self):
        chord_dir = picked(self.attr_dir_btns) == "和弦查属性"
        static = picked(self.as_kind_btns) == "静态"

        set_visible(self.ca_box, chord_dir, dp(38 + 40 + 6 + 22) if chord_dir else 0)
        set_visible(self.as_box, not chord_dir,
                    dp(38 + (80 if static else 160) + (66 if static else 110) + 80 + 22) if not chord_dir else 0)

        self.lbl_ca_hint.text = ("请输入一个和弦，如 C E G" if picked(self.ca_kind_btns) == "静态（1 个和弦）"
                                 else "请输入两个和弦，用 / 隔开，如 C E G / D F A")
        if static:
            set_visible(self.row_c3, False)
            set_visible(self.row_c4, False)
            self.lbl_c1.text = "温度条件："
            self.lbl_c2.text = "张力条件："
            self.lbl_as_hint.text = ("温度：大暖、7、6-8、-8~-6；静态张力=等级：5a、7（组7 全部）、0.645（就近等级）、"
                                     "4-6（组4~组6）；两个都填或只填一个（至少一个）。")
        else:
            set_visible(self.row_c3, True, dp(40))
            set_visible(self.row_c4, True, dp(40))
            self.lbl_c1.text = "温度条件："
            self.lbl_c2.text = "张力条件："
            self.lbl_c3.text = "温度差条件（1~20）："
            self.lbl_c4.text = "张力差条件（1~10）："
            self.lbl_as_hint.text = ("温度：大暖、7、6-8、-8~-6；动态张力按 2 度带（0-2、2-4 … 18-20）：7.5、6-12，"
                                     "范围 0~20。差值按档号（和弦2 减和弦1）：温度差 档1 = -20~-18 … 档10 = -2~0、"
                                     "档11 = 0~2 … 档20 = 18~20；张力差 档1 = -10~-8 … 档5 = -2~0、档6 = 0~2 … "
                                     "档10 = 8~10；可输档号或闭区间（如 10、3-5）。四行可随意混填、至少一个，同时生效。")

    def _run_attr(self):
        if picked(self.attr_dir_btns) == "和弦查属性":
            text = self.ent_ca.text.strip()
            if not text:
                self.status.text = "请先输入和弦"
                return
            self._start_job(lambda: core_single(text), self.box_attr)
            return
        t_text = self.ent_c1.text
        x_text = self.ent_c2.text
        td_text = self.ent_c3.text
        xd_text = self.ent_c4.text
        mode = "all" if picked(self.as_mode_btns) == "全部输出" else "one"
        con_text = self.ent_as_con.text
        if picked(self.as_kind_btns) == "静态":
            work = lambda: core_attr_static(t_text, x_text, mode, con_text)
        else:
            work = lambda: core_attr_dynamic(t_text, x_text, td_text, xd_text, mode, con_text)
        self._start_job(work, self.box_attr)

    # ---------- 页签 5：生成 ----------
    def _build_tab_gen(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(Label(text="起点和弦：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(76)))
        self.ent_gen_start = entry(hint="如 C E G")
        self.ent_gen_start.bind(on_text_validate=lambda *_: self._run_gen())
        row.add_widget(self.ent_gen_start)
        box.add_widget(row)

        box.add_widget(hint_label("下一个和弦的条件（六行可混填、至少一行；也可只填约束）：", self))

        def cond_row(label_text, hint):
            r = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
            r.add_widget(Label(text=label_text, font_name=FONT, font_size=sp(12), size_hint_x=None, width=dp(126)))
            ent = entry(hint=hint)
            ent.bind(on_text_validate=lambda *_: self._run_gen())
            r.add_widget(ent)
            return r, ent

        self.row_g1, self.ent_gen_c1 = cond_row("动态温度：", "大暖、7、6-8、-8~-6")
        box.add_widget(self.row_g1)
        self.row_g2, self.ent_gen_c2 = cond_row("动态张力：", "7.5、6-12，范围 0~20")
        box.add_widget(self.row_g2)
        self.row_g3, self.ent_gen_c3 = cond_row("温度差(1~20)：", "档号或闭区间，和弦2 减和弦1")
        box.add_widget(self.row_g3)
        self.row_g4, self.ent_gen_c4 = cond_row("张力差(1~10)：", "档号或闭区间，和弦2 减和弦1")
        box.add_widget(self.row_g4)
        self.row_g5, self.ent_gen_c5 = cond_row("和弦2 静态温度：", "大暖、7、6-8、-8~-6")
        box.add_widget(self.row_g5)
        self.row_g6, self.ent_gen_c6 = cond_row("和弦2 静态张力：", "5a、7、0.645、4-6")
        box.add_widget(self.row_g6)

        row_con = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row_con.add_widget(Label(text="约束：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        self.ent_gen_con = entry(hint="含 C E、4音、3-4音，可留空")
        self.ent_gen_con.bind(on_text_validate=lambda *_: self._run_gen())
        row_con.add_widget(self.ent_gen_con)
        box.add_widget(row_con)

        row_mode = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(4))
        row_mode.add_widget(Label(text="输出：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        mode_box, self.gen_mode_btns = toggle_row(["随机一个", "全部输出"], "gen_mode", "随机一个")
        mode_box.size_hint_x = 1
        row_mode.add_widget(mode_box)
        row_mode.add_widget(flat_button("生成", lambda *_: self._run_gen()))
        box.add_widget(row_mode)

        box.add_widget(hint_label(
            "给一个起点和弦（如 C E G），按条件生成符合的下一个和弦；条件作用于“下一个和弦”，"
            "差值 = 下一个和弦 减 起点和弦。全部输出＝命中数 + 最多 20 条随机示例。", self))
        self.box_gen = result_box()
        box.add_widget(self.box_gen)
        self.tab_gen_item.add_widget(box)

    def _run_gen(self):
        start = self.ent_gen_start.text.strip()
        if not start:
            self.status.text = "请先输入起点和弦（如 C E G）"
            return
        t_text = self.ent_gen_c1.text
        x_text = self.ent_gen_c2.text
        td_text = self.ent_gen_c3.text
        xd_text = self.ent_gen_c4.text
        st_text = self.ent_gen_c5.text
        sx_text = self.ent_gen_c6.text
        mode = "all" if picked(self.gen_mode_btns) == "全部输出" else "one"
        con_text = self.ent_gen_con.text
        self._start_job(
            lambda: core_generate(start, t_text, x_text, td_text, xd_text, st_text, sx_text, mode, con_text),
            self.box_gen)

    # ---------- 通用 ----------
    def _clear(self, widget, box):
        widget.text = ""
        box.text = ""


if __name__ == "__main__":
    ChordApp().run()
