$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$logDir = Join-Path $scriptDir 'var/local-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'python-service.log'
$stdoutLogFile = Join-Path $logDir 'python-service.out.log'
$bootstrapLogFile = Join-Path $logDir 'python-service-bootstrap.log'
$qdrantLogFile = Join-Path $logDir 'qdrant.log'
$qdrantErrLogFile = Join-Path $logDir 'qdrant.err.log'

function Write-BootstrapLog {
    param(
        [Parameter(Mandatory = $true)]
        [string]$Message
    )

    $Message | Out-File -FilePath $bootstrapLogFile -Append -Encoding utf8
}

function Resolve-PythonLauncher {
    $venvPython = Join-Path $scriptDir '.venv\Scripts\python.exe'
    if (Test-Path $venvPython) {
        return [pscustomobject]@{
            Command = $venvPython
            Args    = @()
            Label   = '.venv'
        }
    }

    $py = Get-Command py -ErrorAction SilentlyContinue
    if ($py) {
        return [pscustomobject]@{
            Command = $py.Source
            Args    = @('-3.11')
            Label   = 'py -3.11'
        }
    }

    $python = Get-Command python -ErrorAction SilentlyContinue
    if ($python) {
        return [pscustomobject]@{
            Command = $python.Source
            Args    = @()
            Label   = 'python'
        }
    }

    $python3 = Get-Command python3 -ErrorAction SilentlyContinue
    if ($python3) {
        return [pscustomobject]@{
            Command = $python3.Source
            Args    = @()
            Label   = 'python3'
        }
    }

    return $null
}

function Test-QdrantHealthy {
    try {
        $curl = Get-Command curl.exe -ErrorAction SilentlyContinue
        if ($curl) {
            & $curl.Source -fsS 'http://127.0.0.1:6333/healthz' *> $null
            return ($LASTEXITCODE -eq 0)
        }

        $response = Invoke-WebRequest -Uri 'http://127.0.0.1:6333/healthz' -TimeoutSec 2 -ErrorAction Stop
        return ($null -ne $response)
    } catch {
        try {
            return [bool](Test-NetConnection 127.0.0.1 -Port 6333 -InformationLevel Quiet)
        } catch {
            return $false
        }
    }
}

function Resolve-QdrantDirectory {
    $candidateRoots = @()
    if ($env:QDRANT_DIR) {
        $candidateRoots += $env:QDRANT_DIR
    }
    $candidateRoots += @(
        'D:\software\qdrant',
        'C:\Program Files\Qdrant',
        'C:\Program Files\qdrant'
    )

    foreach ($candidateRoot in $candidateRoots) {
        if ([string]::IsNullOrWhiteSpace($candidateRoot)) {
            continue
        }

        $candidateExe = Join-Path $candidateRoot 'qdrant.exe'
        if (Test-Path $candidateExe) {
            return $candidateRoot
        }
    }

    $command = Get-Command qdrant.exe -ErrorAction SilentlyContinue
    if ($command) {
        return Split-Path -Parent $command.Source
    }

    return $null
}

function Wait-QdrantHealthy {
    param(
        [int]$MaxAttempts = 20
    )

    for ($i = 0; $i -lt $MaxAttempts; $i++) {
        if (Test-QdrantHealthy) {
            return $true
        }
        Start-Sleep -Seconds 1
    }

    return $false
}

function Start-QdrantIfNeeded {
    if (Test-QdrantHealthy) {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Qdrant 已在运行: http://127.0.0.1:6333"
        return
    }

    $qdrantDir = Resolve-QdrantDirectory
    if (-not $qdrantDir) {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [WARN] 未找到 Qdrant 安装目录或 qdrant.exe。请通过环境变量 QDRANT_DIR 覆盖，或先手动启动 Qdrant。"
        return
    }

    $qdrantExe = Join-Path $qdrantDir 'qdrant.exe'
    Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动 Qdrant: $qdrantExe"
    try { Set-Content -Path $qdrantLogFile -Value '' -Encoding utf8 -ErrorAction Stop } catch { }
    try { Set-Content -Path $qdrantErrLogFile -Value '' -Encoding utf8 -ErrorAction Stop } catch { }

    try {
        Start-Process `
            -FilePath $qdrantExe `
            -WorkingDirectory $qdrantDir `
            -RedirectStandardOutput $qdrantLogFile `
            -RedirectStandardError $qdrantErrLogFile `
            -WindowStyle Hidden `
            -PassThru -ErrorAction Stop | Out-Null
    } catch {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [ERROR] Qdrant 启动命令执行失败: $($_.Exception.Message)"
        throw
    }

    if (Wait-QdrantHealthy) {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] Qdrant 启动成功: http://127.0.0.1:6333"
        return
    }

    Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] [ERROR] Qdrant 启动后仍未通过健康检查，请查看日志: $qdrantLogFile 和 $qdrantErrLogFile"
    throw "Qdrant 启动失败"
}

$launcher = Resolve-PythonLauncher
if (-not $launcher) {
    Write-BootstrapLog ("[{0}] [ERROR] 未找到可用的 Python 解释器或项目虚拟环境。" -f (Get-Date -Format 'yyyy-MM-dd HH:mm:ss'))
    exit 1
}

$env:PYTHONPATH = 'src'
$env:PYTHONUNBUFFERED = '1'
$env:no_proxy = 'localhost,127.0.0.1,::1'
$env:NO_PROXY = 'localhost,127.0.0.1,::1'

$timestamp = Get-Date -Format 'yyyy-MM-dd HH:mm:ss'
Write-BootstrapLog "[$timestamp] 使用启动器: $($launcher.Label)"
Write-BootstrapLog "[$timestamp] 工作目录: $(Get-Location)"

Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动前检查 Qdrant。"
Start-QdrantIfNeeded

Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动前检查本地生活 Qdrant 集合。"
$cmdStr = "`"$($launcher.Command)`" $($launcher.Args -join ' ') -m learning_agent_service.bootstrap.local_life"
cmd.exe /c "$cmdStr >> `"$bootstrapLogFile`" 2>&1"
if ($LASTEXITCODE -ne 0) {
    Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 本地生活 Qdrant 集合预热失败，ExitCode=$LASTEXITCODE。"
    exit $LASTEXITCODE
}
Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 本地生活 Qdrant 集合预热完成。"
Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动命令: $($launcher.Command) $($launcher.Args -join ' ') -m uvicorn app:app --host 127.0.0.1 --port 8000"

$argumentList = @($launcher.Args + @('-m', 'uvicorn', 'app:app', '--host', '127.0.0.1', '--port', '8000'))
try { Set-Content -Path $logFile -Value '' -Encoding utf8 -ErrorAction Stop } catch { }
try { Set-Content -Path $stdoutLogFile -Value '' -Encoding utf8 -ErrorAction Stop } catch { }

try {
    $process = Start-Process `
        -FilePath $launcher.Command `
        -ArgumentList $argumentList `
        -WorkingDirectory $scriptDir `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $logFile `
        -WindowStyle Hidden `
        -PassThru -ErrorAction Stop
} catch {
    Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 警告：进程启动失败（回退模式）。"
    $process = Start-Process `
        -FilePath $launcher.Command `
        -ArgumentList $argumentList `
        -WorkingDirectory $scriptDir `
        -RedirectStandardOutput $stdoutLogFile `
        -RedirectStandardError $logFile `
        -WindowStyle Hidden `
        -PassThru
}

for ($i = 0; $i -lt 5; $i++) {
    Start-Sleep -Seconds 1
    if (Get-NetTCPConnection -LocalPort 8000 -ErrorAction SilentlyContinue) {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 端口 8000 已监听。"
        exit 0
    }
    if ($process.HasExited) {
        Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动进程提前退出，ExitCode=$($process.ExitCode)。"
        exit $process.ExitCode
    }
}

Write-BootstrapLog "[$(Get-Date -Format 'yyyy-MM-dd HH:mm:ss')] 启动进程仍在运行，等待后续健康检查。"
exit 0
