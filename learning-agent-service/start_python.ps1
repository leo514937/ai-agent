$ErrorActionPreference = 'Stop'

$scriptDir = Split-Path -Parent $MyInvocation.MyCommand.Path
Set-Location $scriptDir

$logDir = Join-Path $scriptDir 'var/local-logs'
New-Item -ItemType Directory -Force -Path $logDir | Out-Null
$logFile = Join-Path $logDir 'python-service.log'
$stdoutLogFile = Join-Path $logDir 'python-service.out.log'
$bootstrapLogFile = Join-Path $logDir 'python-service-bootstrap.log'

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
