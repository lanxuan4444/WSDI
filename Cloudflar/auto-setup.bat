@echo off
title Cloudflare 隧道配置
chcp 65001 >nul
setlocal enabledelayedexpansion
D:
cd \Cloudflar

set TOKEN=cfut_DM7F1Czq7gKoeMqtk0dkqCn4ok7iJdl6UxUDT8Wxc4a2ff5b

echo ========================================
echo   正在自动配置 Cloudflare 隧道...
echo ========================================
echo.

:: Step 1: 获取账号 ID
echo [1/5] 获取账号信息...
curl -s -X GET "https://api.cloudflare.com/client/v4/user/tokens/verify" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" > token_verify.json 2>nul

for /f "tokens=*" %%i in ('powershell -Command "(Get-Content token_verify.json | ConvertFrom-Json).result.id"') do set ACCOUNT_ID=%%i

if "!ACCOUNT_ID!"=="" (
    echo 无法获取账号 ID，检查 Token 是否有效
    type token_verify.json
    pause
    exit /b 1
)
echo 账号 ID: !ACCOUNT_ID!
echo.

:: Step 2: 检查是否已有隧道
echo [2/5] 检查现有隧道...
curl -s -X GET "https://api.cloudflare.com/client/v4/accounts/!ACCOUNT_ID!/cfd_tunnel?name=mytunnel" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" > tunnel_list.json 2>nul

powershell -Command "$r=(Get-Content tunnel_list.json | ConvertFrom-Json); if($r.result -and $r.result.Count -gt 0){$r.result[0].id}" > tunnel_id.txt
set /p OLD_ID=<tunnel_id.txt

if not "!OLD_ID!"=="" (
    echo 发现已有隧道: !OLD_ID!
    echo 正在删除...
    curl -s -X DELETE "https://api.cloudflare.com/client/v4/accounts/!ACCOUNT_ID!/cfd_tunnel/!OLD_ID!" -H "Authorization: Bearer %TOKEN%"
    echo 已删除
    echo.
)

:: Step 3: 创建新隧道
echo [3/5] 正在创建命名隧道...
curl -s -X POST "https://api.cloudflare.com/client/v4/accounts/!ACCOUNT_ID!/cfd_tunnel" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" -d "{\"name\":\"mytunnel\",\"config_src\":\"cloudflare\"}" > tunnel_create.json 2>nul

powershell -Command "$r=(Get-Content tunnel_create.json | ConvertFrom-Json); Write-Host $r.result.id; Write-Host $r.result.token" > tunnel_info.txt
set /p TUNNEL_ID=<tunnel_info.txt

if "!TUNNEL_ID!"=="" (
    echo 创建失败！API 返回:
    type tunnel_create.json
    pause
    exit /b 1
)
echo 隧道 ID: !TUNNEL_ID!
echo.

:: Step 4: 生成 config.yml
echo [4/5] 正在生成配置文件...
(
echo tunnel: !TUNNEL_ID!
echo credentials-file: C:\Users\Administrator\.cloudflared\!TUNNEL_ID!.json
echo.
echo ingress:
echo   - hostname: mydata.djyanhong09.workers.dev
echo     service: http://localhost:8080
echo   - service: http_status:404
) > config.yml

:: Step 5: 写入凭据文件
echo [5/5] 正在写入凭据文件...
if not exist "C:\Users\Administrator\.cloudflared" mkdir "C:\Users\Administrator\.cloudflared"

curl -s -X GET "https://api.cloudflare.com/client/v4/accounts/!ACCOUNT_ID!/cfd_tunnel/!TUNNEL_ID!/token" -H "Authorization: Bearer %TOKEN%" -H "Content-Type: application/json" > tunnel_token.json 2>nul

powershell -Command "$r=(Get-Content tunnel_token.json | ConvertFrom-Json); if($r.result){[IO.File]::WriteAllText('C:\Users\Administrator\.cloudflared\!TUNNEL_ID!.json',$r.result | ConvertTo-Json -Compress)}"

:: 清理临时文件
del token_verify.json tunnel_list.json tunnel_create.json tunnel_token.json tunnel_id.txt tunnel_info.txt 2>nul

echo.
echo ========================================
echo   ✅ 配置完成！
echo ========================================
echo.
echo 📋 你的隧道 UUID (复制这个):
echo.
echo    !TUNNEL_ID!
echo.
echo.
echo 📝 Worker 代码 (复制到 mydata Worker 替换):
echo ========================================
(
echo export default {^
echo   async fetch^(request^) {^
echo     const TUNNEL_ID = '!TUNNEL_ID!';^
echo     const url = new URL^(request.url^);^
echo     const target = "https://"+TUNNEL_ID+".cfargotunnel.com"+url.pathname+url.search;^
echo     const headers = new Headers^(request.headers^);^
echo     headers.set^('Host', TUNNEL_ID+'.cfargotunnel.com'^);^
echo     const newReq = new Request^(target, {method:request.method, headers, body:request.body, redirect:'follow'}^);^
echo     try { return await fetch^(newReq^); }^
echo     catch^(e^) { return new Response^("隧道未连接: " + e.message, {status:502}^); }^
echo   }^
echo }
) > worker-code.js

type worker-code.js
echo ========================================
echo.
echo 🚀 启动: 双击【启动隧道.bat】
echo 🌐 访问: https://mydata.djyanhong09.workers.dev
echo.
pause
