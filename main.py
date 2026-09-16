# -*- coding: utf-8 -*-
"""和弦张力等级查询工具 —— 手机界面版（Kivy）

电脑上预览：在仓库根目录执行  python mobile/main.py
打包安卓 APK：见 mobile/README.md

本文件不改动命令行程序 src/chord_calculate.py：只 import 它、复用其中全部
计算与查询函数（query_single / search_static / search_dynamic /
search_static_attr / search_dynamic_attr / search_diff_attr 等），
输出用 redirect_stdout 原样接住显示 —— 与桌面版 src/chord_ui.py 同一套做法，
算法/数据/文案只有一份。

四个页签与桌面版一致：
  查询 —— 单和弦 / 和声进行
  等级 —— 温度 11 档查找（静态 / 动态 / 两个都查；随机一个 / 全部输出）
  批量 —— 每行一个和弦
  查   —— 和弦查属性；属性查和弦（静态 / 动态[动态温度/张力档 或 差值]）

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
from kivy.uix.spinner import Spinner
from kivy.uix.tabbedpanel import TabbedPanel, TabbedPanelItem
from kivy.uix.textinput import TextInput
from kivy.uix.togglebutton import ToggleButton

# 结果区/输入框统一字体；中文字形在安卓上必须显式指定，否则是方框
FONT = "CJK"


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


def core_grade(name, kinds, mode):
    """等级查找。kinds 是 ("静态",) / ("动态",) / ("静态", "动态")；mode 是 "one" / "all"。"""
    grade = cc.resolve_grade(name)
    out = ["", f"温度等级查找：{grade}", "-" * 60]
    if "静态" in kinds:
        out.append(_capture(cc.search_static, grade, mode).rstrip("\n"))
    if "动态" in kinds:
        out.append(_capture(cc.search_dynamic, grade, mode).rstrip("\n"))
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


def core_attr_static(t_text, x_text, mode):
    """属性查和弦（静态）：温度条件 × 张力条件，至少输一个。"""
    t_text, x_text = t_text.strip(), x_text.strip()
    if not t_text and not x_text:
        return "  温度和张力至少输一个。\n"
    grade_set = level_set = None
    desc_parts = []
    if t_text:
        cond = cc.parse_temperature_cond(t_text)
        if cond is None:
            return f"  温度条件“{t_text}”无法识别（可用：大暖、7、6-8、-8~-6）。\n"
        names, disp = cond
        desc_parts.append(f"温度 {disp}")
        grade_set = names
    if x_text:
        cond = cc.parse_static_tension_cond(x_text)
        if cond is None:
            return f"  张力条件“{x_text}”无法识别（可用：5a、7、0.645、4-6）。\n"
        level_set, disp = cond
        desc_parts.append(f"张力 {disp}")
    desc = " × ".join(desc_parts)
    return "-" * 60 + "\n" + _capture(cc.search_static_attr, grade_set, level_set, desc, mode)


def core_attr_dynamic(t_text, x_text, mode):
    """属性查和弦（动态）：温度条件 × 动态张力带条件，至少输一个。"""
    t_text, x_text = t_text.strip(), x_text.strip()
    if not t_text and not x_text:
        return "  温度和张力至少输一个。\n"
    gi_set = k2_set = None
    desc_parts = []
    if t_text:
        cond = cc.parse_temperature_cond(t_text)
        if cond is None:
            return f"  温度条件“{t_text}”无法识别（可用：大暖、7、6-8、-8~-6）。\n"
        names, disp = cond
        desc_parts.append(f"温度 {disp}")
        gi_set = {cc.TEMP_GRADES.index(g) for g in names}
    if x_text:
        cond = cc.parse_dynamic_tension_cond(x_text)
        if cond is None:
            return f"  张力条件“{x_text}”无法识别（动态可用：7.5、6-12，范围 0~20）。\n"
        k2_set, disp = cond
        desc_parts.append(f"张力 {disp}")
    desc = " × ".join(desc_parts)
    return "-" * 60 + "\n" + _capture(cc.search_dynamic_attr, gi_set, k2_set, desc, mode)


def core_diff(t_text, x_text, mode):
    """差值查对：温度差档号 × 张力差档号，至少输一个。"""
    t_text, x_text = t_text.strip(), x_text.strip()
    if not t_text and not x_text:
        return "  温度差和张力差至少输一个。\n"
    kt_set = kx_set = None
    desc_parts = []
    if t_text:
        cond = cc.parse_diff_band_cond(t_text, 20)
        if cond is None:
            return f"  温度差条件“{t_text}”无法识别（可输档号 1~20，区间如 3-5）。\n"
        kt_set, disp = cond
        desc_parts.append(f"温度差 {disp}")
    if x_text:
        cond = cc.parse_diff_band_cond(x_text, 10)
        if cond is None:
            return f"  张力差条件“{x_text}”无法识别（可输档号 1~10，区间如 3-5）。\n"
        kx_set, disp = cond
        desc_parts.append(f"张力差 {disp}")
    desc = " × ".join(desc_parts)
    return "-" * 60 + "\n" + _capture(cc.search_diff_attr, kt_set, kx_set, desc, mode)


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


def result_box():
    """只读结果区：可滚动、可选中复制，但改不了。"""
    ti = TextInput(text="", readonly=True, multiline=True, font_name=FONT, font_size=sp(13),
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


# ========== 主界面 ==========
class ChordApp(App):
    title = "和弦张力等级查询工具"

    def build(self):
        self._pending = 0
        self._result_target = None

        root = BoxLayout(orientation="vertical")
        self.status = Label(text="就绪", font_name=FONT, font_size=sp(12),
                            size_hint_y=None, height=dp(26),
                            color=(0.9, 0.9, 0.94, 1), halign="left", valign="middle")
        self.status.bind(size=lambda w, v: setattr(w, "text_size", (v[0] - dp(12), v[1])))
        self.status.padding = [dp(6), 0, dp(6), 0]

        self.tp = TabbedPanel(do_default_tab=False, tab_pos="top_mid", tab_height=dp(36))
        self.tab_query_item = TabbedPanelItem(text=" 查询 ", font_name=FONT)
        self.tab_grade_item = TabbedPanelItem(text=" 等级 ", font_name=FONT)
        self.tab_batch_item = TabbedPanelItem(text=" 批量 ", font_name=FONT)
        self.tab_attr_item = TabbedPanelItem(text=" 查 ", font_name=FONT)
        for item in (self.tab_query_item, self.tab_grade_item,
                     self.tab_batch_item, self.tab_attr_item):
            self.tp.add_widget(item)

        self._build_tab_query()
        self._build_tab_grade()
        self._build_tab_batch()
        self._build_tab_attr()

        root.add_widget(self.tp)
        root.add_widget(self.status)
        return root

    def on_start(self):
        if IS_ANDROID:
            try:
                Window.softinput_mode = "below_target"
            except Exception:
                pass

    # ---------- 查询调度 ----------
    def _start_job(self, work, target):
        """后台线程跑查询；同一时刻只允许一个，跑完经 Clock 回主线程显示。"""
        if self._pending:
            self.status.text = "上一个查询还在跑，稍等…"
            return
        self._pending += 1
        self._result_target = target
        self.status.text = "查询中…"
        t0 = time.perf_counter()

        def runner():
            try:
                content = work()
            except Exception as exc:  # 保底：出错也只显示在结果区，不让程序崩
                content = f"  出错了：{exc}\n"
            dt = time.perf_counter() - t0
            Clock.schedule_once(lambda _dt: self._finish(content, dt), 0)

        threading.Thread(target=runner, daemon=True).start()

    def _finish(self, content, dt):
        self._pending -= 1
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
            "输 等级名（如 巨暖）会跳到「等级」页；输 查 / batch 会跳到对应页。", self))
        self.box_query = result_box()
        box.add_widget(self.box_query)
        self.tab_query_item.add_widget(box)

    def _run_query(self):
        text = self.ent_query.text.strip()
        if not text:
            self.status.text = "请先输入和弦"
            return
        if text in ("查", "查询"):
            self.tp.switch_to(self.tab_attr_item)
            self.status.text = "已跳到「查」页"
            return
        if text.lower() == "batch":
            self.tp.switch_to(self.tab_batch_item)
            self.status.text = "已跳到「批量」页"
            return
        grade = cc.resolve_grade(text)
        if grade:
            self.tp.switch_to(self.tab_grade_item)
            self.grade_spin.text = grade
            self.status.text = f"“{text}”是温度等级名，已跳到「等级」页，点「查询」即可"
            return
        self._start_job(lambda: core_single(text), self.box_query)

    # ---------- 页签 2：等级查找 ----------
    def _build_tab_grade(self):
        box = BoxLayout(orientation="vertical", padding=dp(8), spacing=dp(4))
        row = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        row.add_widget(Label(text="温度等级：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(76)))
        self.grade_spin = Spinner(text="巨暖", values=cc.TEMP_GRADES, font_name=FONT,
                                  font_size=sp(13), size_hint_y=None, height=dp(40))
        row.add_widget(self.grade_spin)
        box.add_widget(row)

        row2, self.grade_kind_btns = toggle_row(["静态", "动态", "两个都查"], "grade_kind", "静态")
        box.add_widget(Label(text="查哪种：", font_name=FONT, font_size=sp(13), size_hint_y=None, height=dp(20)))
        box.add_widget(row2)

        row3, self.grade_mode_btns = toggle_row(["随机一个", "全部输出"], "grade_mode", "随机一个")
        box.add_widget(Label(text="输出：", font_name=FONT, font_size=sp(13), size_hint_y=None, height=dp(20)))
        box.add_widget(row3)
        box.add_widget(flat_button("查询", lambda *_: self._run_grade()))
        box.add_widget(hint_label(
            "每档 2 度：巨冷 大冷 中冷 小冷 微冷 平衡（中性） 微暖 小暖 中暖 大暖 巨暖；"
            "零值（平衡/中性 两种标签）合并进中间档。动态“全部输出”＝总数 + 20 条随机示例。", self))
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
        self._start_job(lambda: core_grade(grade, kinds, mode), self.box_grade)

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

        # 方向二：属性查和弦（静态 / 动态[动态温度/张力档 或 差值]）
        self.as_box = BoxLayout(orientation="vertical", spacing=dp(2), size_hint_y=None, height=dp(1))
        row_as, self.as_kind_btns = toggle_row(["静态", "动态"], "as_kind", "静态")
        self.as_box.add_widget(row_as)
        self.as_sub_row, self.as_dyn_btns = toggle_row(["动态温度/张力档", "温度差/张力差（差值）"], "as_dyn", "动态温度/张力档")
        self.as_box.add_widget(self.as_sub_row)
        row_c1 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.lbl_c1 = Label(text="温度条件：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(112))
        self.ent_c1 = entry()
        self.ent_c1.bind(on_text_validate=lambda *_: self._run_attr())
        row_c1.add_widget(self.lbl_c1)
        row_c1.add_widget(self.ent_c1)
        self.as_box.add_widget(row_c1)
        row_c2 = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(6))
        self.lbl_c2 = Label(text="张力条件：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(112))
        self.ent_c2 = entry()
        self.ent_c2.bind(on_text_validate=lambda *_: self._run_attr())
        row_c2.add_widget(self.lbl_c2)
        row_c2.add_widget(self.ent_c2)
        self.as_box.add_widget(row_c2)
        self.lbl_as_hint = hint_label("", self)
        self.as_box.add_widget(self.lbl_as_hint)
        row_mode = BoxLayout(orientation="horizontal", size_hint_y=None, height=dp(40), spacing=dp(4))
        row_mode.add_widget(Label(text="输出：", font_name=FONT, font_size=sp(13), size_hint_x=None, width=dp(44)))
        mode_box, self.as_mode_btns = toggle_row(["随机一个", "全部输出"], "as_mode", "随机一个")
        mode_box.size_hint_x = 1
        row_mode.add_widget(mode_box)
        row_mode.add_widget(flat_button("查询", lambda *_: self._run_attr()))
        self.as_box.add_widget(row_mode)
        self.as_box.height = dp(38 + 38 + 40 + 40 + 40 + 22 + 40 + 20)
        box.add_widget(self.as_box)

        self.box_attr = result_box()
        box.add_widget(self.box_attr)
        self.tab_attr_item.add_widget(box)

        for btn in self.attr_dir_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())
        for btn in self.as_kind_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())
        for btn in self.as_dyn_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())
        for btn in self.ca_kind_btns.values():
            btn.bind(on_press=lambda *_: self._refresh_attr())

        self._refresh_attr()

    def _refresh_attr(self):
        chord_dir = picked(self.attr_dir_btns) == "和弦查属性"
        static = picked(self.as_kind_btns) == "静态"
        diff = (not static) and picked(self.as_dyn_btns) == "温度差/张力差（差值）"

        set_visible(self.ca_box, chord_dir, dp(38 + 40 + 6 + 22) if chord_dir else 0)
        set_visible(self.as_box, not chord_dir,
                    dp(38 + (0 if static else 38) + 40 + 40 + 40 + 22 + 40 + 20) if not chord_dir else 0)
        set_visible(self.as_sub_row, not static, dp(38))

        self.lbl_ca_hint.text = ("请输入一个和弦，如 C E G" if picked(self.ca_kind_btns) == "静态（1 个和弦）"
                                 else "请输入两个和弦，用 / 隔开，如 C E G / D F A")
        if static:
            self.lbl_c1.text = "温度条件："
            self.lbl_c2.text = "张力条件："
            self.lbl_as_hint.text = ("温度：大暖、7、6-8、-8~-6；静态张力=等级：5a、7（组7 全部）、0.645（就近等级）、"
                                     "4-6（组4~组6）；两个都填或只填一个（至少一个）。")
        elif not diff:
            self.lbl_c1.text = "温度条件："
            self.lbl_c2.text = "张力条件："
            self.lbl_as_hint.text = ("温度：大暖、7、6-8、-8~-6；动态张力按 2 度带（0-2、2-4 … 18-20）：7.5、6-12，"
                                     "范围 0~20；两个都填或只填一个（至少一个）。")
        else:
            self.lbl_c1.text = "温度差条件 1~20："
            self.lbl_c2.text = "张力差条件 1~10："
            self.lbl_as_hint.text = ("按档号（和弦2 减和弦1）：温度差 档1 = -20~-18 … 档10 = -2~0、档11 = 0~2 … 档20 = 18~20；"
                                     "张力差 档1 = -10~-8 … 档5 = -2~0、档6 = 0~2 … 档10 = 8~10；"
                                     "可输档号或闭区间（如 10、3-5），至少一个。")

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
        mode = "all" if picked(self.as_mode_btns) == "全部输出" else "one"
        static = picked(self.as_kind_btns) == "静态"
        diff = (not static) and picked(self.as_dyn_btns) == "温度差/张力差（差值）"
        if static:
            work = lambda: core_attr_static(t_text, x_text, mode)
        elif diff:
            work = lambda: core_diff(t_text, x_text, mode)
        else:
            work = lambda: core_attr_dynamic(t_text, x_text, mode)
        self._start_job(work, self.box_attr)

    # ---------- 通用 ----------
    def _clear(self, widget, box):
        widget.text = ""
        box.text = ""


if __name__ == "__main__":
    ChordApp().run()
