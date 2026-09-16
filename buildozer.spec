[app]
# 应用显示名（手机图标下面那行字）
title = 和弦工具

# 应用包名：org.chord.chordtool
package.name = chordtool
package.domain = org.chord

# 源码目录就是本目录（mobile/），入口是 main.py
source.dir = .
source.include_exts = py,png,jpg,kv,atlas,ttf,otf,ttc,txt
source.exclude_dirs = __pycache__, .github, bin, .buildozer

version = 0.1

# 本程序纯标准库 + Kivy，没有其他第三方依赖
requirements = python3,kivy

# 界面是竖屏的
orientation = portrait
fullscreen = 0

log_level = 2

# 只打 64 位包（现在手机基本都是 arm64；要支持很老的机器再加 armeabi-v7a）
android.archs = arm64-v8a
android.api = 34
android.minapi = 24

# 完全离线的小工具，不需要任何权限
android.permissions =

# 云端构建时自动接受安卓 SDK 的许可协议（GitHub Actions 里没人能手动按 y）
android.accept_sdk_license = True

android.allow_backup = True
