@echo off
setlocal EnableExtensions DisableDelayedExpansion
chcp 65001 >nul 2>&1
title WorkBuddy 模型配置工具

set "DEFAULT_API_BASE_URL=https://work.xclawxx.top/v1"
set "FALLBACK_API_BASE_URL=https://work-gz.aicodee.com/v1"
setlocal EnableDelayedExpansion

:SELECT_LINE
echo.
echo 请选择接口线路：
echo   1. 默认线路（推荐）  !DEFAULT_API_BASE_URL!
echo   2. 国内备用线路      !FALLBACK_API_BASE_URL!
echo.
set "LINE_CHOICE="
set /p "LINE_CHOICE=请输入 1 或 2（直接回车 = 1）："
if not defined LINE_CHOICE set "LINE_CHOICE=1"
if "!LINE_CHOICE!"=="1" goto USE_DEFAULT_LINE
if "!LINE_CHOICE!"=="2" goto USE_FALLBACK_LINE
echo.
echo 输入无效，请重新选择。
goto SELECT_LINE

:USE_DEFAULT_LINE
set "API_BASE_URL=!DEFAULT_API_BASE_URL!"
set "LINE_LABEL=默认线路"
goto LINE_SELECTED

:USE_FALLBACK_LINE
set "API_BASE_URL=!FALLBACK_API_BASE_URL!"
set "LINE_LABEL=国内备用线路"

:LINE_SELECTED
setlocal DisableDelayedExpansion
echo.
echo 已选择：%LINE_LABEL%（%API_BASE_URL%）

set "CONFIG_DIR=%USERPROFILE%\.workbuddy"
set "CONFIG_FILE=%CONFIG_DIR%\models.json"
set "TEMP_FILE=%CONFIG_DIR%\.models.json.tmp-%RANDOM%-%RANDOM%"
set "BACKUP_FILE="

if not exist "%CONFIG_DIR%" mkdir "%CONFIG_DIR%"
if errorlevel 1 goto FAILED

if not exist "%CONFIG_FILE%" goto WRITE_CONFIG
set "BACKUP_FILE=%CONFIG_FILE%.backup-%RANDOM%-%RANDOM%"
copy /y "%CONFIG_FILE%" "%BACKUP_FILE%" >nul
if errorlevel 1 goto FAILED

:WRITE_CONFIG
> "%TEMP_FILE%" echo [
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "Auto",
>> "%TEMP_FILE%" echo     "name": "Auto",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u5b98\u65b9\u63a8\u8350:#7900c6",
>> "%TEMP_FILE%" echo       "badge:\u4f4e\u6d88\u8017:#16866f"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "deepseek-v4-flash",
>> "%TEMP_FILE%" echo     "name": "deepseek-v4-flash",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4f4e\u6d88\u8017:#16866f"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "DeepSeek-V4-Flash-plus",
>> "%TEMP_FILE%" echo     "name": "DeepSeek-V4-Flash-plus",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4f4e\u6d88\u8017:#16866f"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "deepseek-v4-pro",
>> "%TEMP_FILE%" echo     "name": "deepseek-v4-pro",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4e2d\u6d88\u8017:#3274a6"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "DeepSeek-V4-Pro-plus",
>> "%TEMP_FILE%" echo     "name": "DeepSeek-V4-Pro-plus",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4e2d\u6d88\u8017:#3274a6"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "glm-5.2",
>> "%TEMP_FILE%" echo     "name": "glm-5.2",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4e2d\u6d88\u8017:#3274a6"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "glm-5.2-max-stable",
>> "%TEMP_FILE%" echo     "name": "glm-5.2-max-stable",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u6781\u9ad8\u6d88\u8017:#a94c4c"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "glm-5.2-stable",
>> "%TEMP_FILE%" echo     "name": "glm-5.2-stable",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u9ad8\u6d88\u8017:#a7681e"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "glm-5.3-stable",
>> "%TEMP_FILE%" echo     "name": "glm-5.3-stable",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u9ad8\u6d88\u8017:#a7681e"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "Kimi-K2.6",
>> "%TEMP_FILE%" echo     "name": "Kimi-K2.6",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4e2d\u6d88\u8017:#3274a6"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "kimi-k3-stable",
>> "%TEMP_FILE%" echo     "name": "kimi-k3-stable",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u6781\u9ad8\u6d88\u8017:#a94c4c"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "MiniMax-M2.7",
>> "%TEMP_FILE%" echo     "name": "MiniMax-M2.7",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4f4e\u6d88\u8017:#16866f"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "MiniMax-M2.7-highspeed",
>> "%TEMP_FILE%" echo     "name": "MiniMax-M2.7-highspeed",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4f4e\u6d88\u8017:#16866f"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   },
>> "%TEMP_FILE%" echo   {
>> "%TEMP_FILE%" echo     "id": "MiniMax-M3",
>> "%TEMP_FILE%" echo     "name": "MiniMax-M3",
>> "%TEMP_FILE%" echo     "vendor": "Custom",
>> "%TEMP_FILE%" echo     "url": "%API_BASE_URL%",
>> "%TEMP_FILE%" echo     "apiKey": "sk-932555ff3186d463eecea9e08b14c390a49c7537274823b9a38e3be3ab99a857",
>> "%TEMP_FILE%" echo     "iconUrl": "https://tool.aicodee.com/work/jisu1.png",
>> "%TEMP_FILE%" echo     "supportsToolCall": true,
>> "%TEMP_FILE%" echo     "supportsImages": true,
>> "%TEMP_FILE%" echo     "supportsReasoning": false,
>> "%TEMP_FILE%" echo     "useCustomProtocol": false,
>> "%TEMP_FILE%" echo     "maxInputTokens": 131072,
>> "%TEMP_FILE%" echo     "maxOutputTokens": 32768,
>> "%TEMP_FILE%" echo     "tags": [
>> "%TEMP_FILE%" echo       "badge:\u4e2d\u6d88\u8017:#3274a6"
>> "%TEMP_FILE%" echo     ]
>> "%TEMP_FILE%" echo   }
>> "%TEMP_FILE%" echo ]
if errorlevel 1 goto FAILED
move /y "%TEMP_FILE%" "%CONFIG_FILE%" >nul
if errorlevel 1 goto FAILED

echo.
echo 配置成功！
echo.
echo 使用线路：%LINE_LABEL%（%API_BASE_URL%）
echo 配置文件：%CONFIG_FILE%
if defined BACKUP_FILE echo 备份文件：%BACKUP_FILE%
echo.
echo 请打开 WorkBuddy，选择自定义模型里的模型（推荐 Auto）使用即可。
echo.
echo 按任意键退出……
pause >nul
exit /b 0

:FAILED
if exist "%TEMP_FILE%" del /f /q "%TEMP_FILE%" >nul 2>&1
echo.
echo 配置失败，原配置文件没有被替换。
if defined BACKUP_FILE echo 备份文件：%BACKUP_FILE%
echo.
echo 请检查文件权限后重新运行。
echo.
echo 按任意键退出……
pause >nul
exit /b 1
