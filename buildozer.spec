[app]
title = DutchPay
package.name = dcw
package.domain = com.jaewoo
source.dir = .
source.include_exts = py,png,jpg,jpeg,ttf,txt,json,html,xml
source.exclude_dirs = .buildozer,bin,__pycache__
version = 1.0
android.api = 34
android.minapi = 24
requirements = python3,kivy,plyer,requests
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,CAMERA,POST_NOTIFICATIONS
android.ndk_version = 28c
android.enable_androidx = True
android.archs = arm64-v8a
p4a.branch = develop
# Register FileProvider in <application>.
# Copy file_paths.xml into res/xml/.
android.res_xml = android_src/main/res/xml/file_paths.xml
[buildozer]
log_level = 2
warn_on_root = 1
