[app]
title = DutchPay
package.name = dcw
package.domain = com.jaewoo
p4a.branch = develop
source.dir = .
source.include_exts = py,kv,png,jpg,jpeg,ttf,xml
source.exclude_patterns = server.py,validation.py,ocr_service.py,test_*.py,*.json,*.db*,*.log
version = 1.1.0
requirements = python3,kivy,plyer,certifi,pyjnius,requests,urllib3
orientation = portrait
fullscreen = 0
android.permissions = INTERNET,CAMERA,POST_NOTIFICATIONS,READ_EXTERNAL_STORAGE,WRITE_EXTERNAL_STORAGE
android.api = 34
android.minapi = 24
android.archs = arm64-v8a
android.enable_androidx = True
android.gradle_dependencies = androidx.core:core:1.12.0
android.extra_manifest_application_xml = android_src/extra_manifest_application.xml
android.res_xml = android_src/main/res/xml/file_paths.xml

[buildozer]
log_level = 2
warn_on_root = 1
