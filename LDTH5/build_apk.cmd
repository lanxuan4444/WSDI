@echo off
rem [2026-09-29 PARTS] LDPartsScanner APK 构建脚本（用已缓存的 gradle-8.7 + C:\Android SDK/JDK17）
setlocal
set "JAVA_HOME=C:\Android\jdk17"
set "PATH=%JAVA_HOME%\bin;%PATH%"
set "GRADLE_BAT=%USERPROFILE%\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat"
cd /d "%~dp0apk\LDPartsScanner"
call "%GRADLE_BAT%" assembleDebug --no-daemon --console=plain %*
exit /b %errorlevel%
