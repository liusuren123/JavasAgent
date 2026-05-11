# JavasAgent Windows 一键安装脚本
# 用法: .\scripts\install.ps1

$ErrorActionPreference = "Stop"

Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  JavasAgent 安装脚本 (Windows)" -ForegroundColor Cyan
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""

# 1. 检查 Python 版本
Write-Host "[1/6] 检查 Python 版本..." -ForegroundColor Yellow

$pythonCmd = $null
foreach ($cmd in @("python", "python3")) {
    try {
        $version = & $cmd --version 2>&1
        if ($version -match "Python (\d+)\.(\d+)") {
            $major = [int]$Matches[1]
            $minor = [int]$Matches[2]
            if ($major -ge 3 -and $minor -ge 11) {
                $pythonCmd = $cmd
                Write-Host "  找到 $version" -ForegroundColor Green
                break
            }
        }
    } catch {}
}

if (-not $pythonCmd) {
    Write-Host "  错误: 需要 Python 3.11+，请先安装 Python" -ForegroundColor Red
    Write-Host "  下载地址: https://www.python.org/downloads/" -ForegroundColor Red
    exit 1
}

# 2. 创建虚拟环境
Write-Host "[2/6] 创建虚拟环境..." -ForegroundColor Yellow

if (Test-Path "venv") {
    Write-Host "  虚拟环境已存在，跳过" -ForegroundColor Gray
} else {
    & $pythonCmd -m venv venv
    if ($LASTEXITCODE -ne 0) {
        Write-Host "  错误: 创建虚拟环境失败" -ForegroundColor Red
        exit 1
    }
    Write-Host "  虚拟环境已创建" -ForegroundColor Green
}

# 激活虚拟环境
& ".\venv\Scripts\Activate.ps1"

# 3. 安装核心依赖
Write-Host "[3/6] 安装核心依赖..." -ForegroundColor Yellow

pip install -e "." 2>&1 | ForEach-Object { Write-Host "  $_" -ForegroundColor Gray }
if ($LASTEXITCODE -ne 0) {
    Write-Host "  错误: 安装核心依赖失败" -ForegroundColor Red
    exit 1
}
Write-Host "  核心依赖安装完成" -ForegroundColor Green

# 4. 安装可选依赖（语音模块）
Write-Host "[4/6] 安装可选依赖（语音模块）..." -ForegroundColor Yellow

$voicePkgs = @("edge-tts")
foreach ($pkg in $voicePkgs) {
    pip install $pkg 2>$null | Out-Null
}

# PyAudio 特殊处理
pip install pyaudio 2>$null | Out-Null
if ($LASTEXITCODE -ne 0) {
    Write-Host "  PyAudio 安装失败，将使用 SoundDevice 替代" -ForegroundColor DarkYellow
    pip install sounddevice 2>$null | Out-Null
}

Write-Host "  可选依赖安装完成（部分可能跳过）" -ForegroundColor Green

# 5. 复制配置模板
Write-Host "[5/6] 检查配置文件..." -ForegroundColor Yellow

if (-not (Test-Path "config\default.yaml")) {
    Write-Host "  警告: config\default.yaml 不存在，请检查" -ForegroundColor DarkYellow
} else {
    Write-Host "  配置文件已就绪" -ForegroundColor Green
}

# 创建数据目录
@("data\memory\chroma", "data\screenshots", "data\logs") | ForEach-Object {
    if (-not (Test-Path $_)) {
        New-Item -ItemType Directory -Path $_ -Force | Out-Null
    }
}
Write-Host "  数据目录已创建" -ForegroundColor Green

# 6. 验证安装
Write-Host "[6/6] 验证安装..." -ForegroundColor Yellow

try {
    $result = python -c "import src; print('OK')" 2>&1
    if ($result -eq "OK") {
        Write-Host "  验证通过！" -ForegroundColor Green
    } else {
        Write-Host "  警告: 模块导入测试未通过，请检查依赖" -ForegroundColor DarkYellow
    }
} catch {
    Write-Host "  警告: 验证失败，请手动检查" -ForegroundColor DarkYellow
}

Write-Host ""
Write-Host "========================================" -ForegroundColor Cyan
Write-Host "  安装完成！" -ForegroundColor Green
Write-Host "========================================" -ForegroundColor Cyan
Write-Host ""
Write-Host "  激活虚拟环境:" -ForegroundColor White
Write-Host "    .\venv\Scripts\Activate.ps1" -ForegroundColor Cyan
Write-Host ""
Write-Host "  启动对话:" -ForegroundColor White
Write-Host "    javas chat" -ForegroundColor Cyan
Write-Host ""
