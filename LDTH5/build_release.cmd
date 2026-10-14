@echo off
rem [v1.08] release 构建（R8 + shrinkResources + debug 签名）
setlocal
set "JAVA_HOME=C:\Android\jdk17"
set "PATH=%JAVA_HOME%\bin;%PATH%"
set "GRADLE_BAT=%USERPROFILE%\.gradle\wrapper\dists\gradle-8.7-bin\bhs2wmbdwecv87pi65oeuq5iu\gradle-8.7\bin\gradle.bat"
cd /d "%~dp0apk\LDPartsScanner"
call "%GRADLE_BAT%" assembleRelease --no-daemon --console=plain %*
exit /b %errorlevel%
