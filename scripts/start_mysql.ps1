$ErrorActionPreference = "Stop"

$MYSQLADMIN = "D:\software\MySQL\bin\mysqladmin.exe"
$MYSQL_USER = "root"
$MYSQL_PASS = "123456"

# Helper: test MySQL connectivity quietly
function Test-MySQL {
    $ping = & cmd /c "`"$MYSQLADMIN`" -u $MYSQL_USER -p$MYSQL_PASS ping 2>nul" 2>&1
    return $LASTEXITCODE -eq 0
}

# Step 1: Check if MySQL is already running
Write-Host "检查 MySQL 状态..." -ForegroundColor Cyan

$existingProc = Get-Process mysqld -ErrorAction SilentlyContinue | Where-Object { $_.Id -ne $pid }
$portCheck = netstat -ano | Select-String ":3306\s"

if ($existingProc -and $portCheck -and (Test-MySQL)) {
    Write-Host "MySQL 已运行，无需启动" -ForegroundColor Green
    exit 0
}

# Step 2: Check if we already have admin rights
$isAdmin = ([Security.Principal.WindowsPrincipal] [Security.Principal.WindowsIdentity]::GetCurrent()).IsInRole([Security.Principal.WindowsBuiltInRole] "Administrator")

if (-not $isAdmin) {
    Write-Host "需要管理员权限来启动 MySQL 服务，正在弹出授权窗口..." -ForegroundColor Yellow
    $scriptPath = if ($PSCommandPath) { $PSCommandPath } else { "$PSScriptRoot\start_mysql.ps1" }
    $fullPath = Resolve-Path $scriptPath
    $p = Start-Process -FilePath "powershell.exe" -Verb RunAs -ArgumentList "-NoProfile -ExecutionPolicy Bypass -File `"$fullPath`"" -PassThru -Wait
    Start-Sleep -Seconds 3
    if (Test-MySQL) {
        Write-Host "MySQL 已成功启动" -ForegroundColor Green
        exit 0
    } else {
        Write-Host "MySQL 启动失败，请检查服务状态" -ForegroundColor Red
        exit 1
    }
}

# Step 3: We have admin rights, start the service
Write-Host "正在启动 MySQL 服务..." -ForegroundColor Cyan
net start mysql

if ($LASTEXITCODE -eq 0) {
    Write-Host "MySQL 服务启动成功" -ForegroundColor Green
    exit 0
} else {
    Write-Host "MySQL 服务启动失败" -ForegroundColor Red
    exit 1
}
