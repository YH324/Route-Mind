# ================================================================
# RouteMind local deployment package builder for Windows PowerShell
# Security rule: .env is never copied into the deployment package.
# ================================================================
[CmdletBinding()]
param(
    [string]$ServerHost = "47.102.142.207",
    [string]$ServerUser = "root",
    [string]$RemotePath = "/opt/routemind",
    [string]$OutFile = ""
)

$ErrorActionPreference = "Stop"
$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path

$EnvFile = Join-Path $ProjectRoot ".env"
if (Test-Path $EnvFile) {
    Write-Host "[SECURITY] .env exists locally and will be excluded from the package." -ForegroundColor Yellow
    Write-Host "           Create .env on the server from .env.example instead." -ForegroundColor Yellow
}

$Timestamp = Get-Date -Format "yyyyMMdd_HHmmss"
$PkgName = "routemind_$Timestamp"
$TempDir = Join-Path $env:TEMP $PkgName
$PkgFile = if ($OutFile) { $OutFile } else { Join-Path $env:TEMP "$PkgName.tar.gz" }

Write-Host "[PACK] Temp directory: $TempDir" -ForegroundColor Cyan
if (Test-Path $TempDir) {
    Remove-Item -LiteralPath $TempDir -Recurse -Force
}
New-Item -ItemType Directory -Path $TempDir | Out-Null

$ExcludePatterns = @(
    ".env",
    ".git",
    ".gitignore",
    ".tmp_venv",
    "__pycache__",
    "*.pyc",
    "*.pyo",
    "*.log",
    "output/*.log",
    "output/poi_embeddings.npy",
    "output/poi_embedding_ids.json",
    "output/poi_descriptions.json",
    "output/user_memory_profiles.json",
    "ugc_groundtruth_v4_xl.json",
    "screenshot*.png",
    "take_screenshot.py",
    "server_launcher.py",
    "web/backup",
    "tests",
    "_test_*.py",
    "test_*.py",
    "test_mimo*.py",
    "generate_*.py",
    "poi_data",
    "routemind*.tar.gz"
)

function Test-Excluded {
    param(
        [string]$Name,
        [string]$RelPath
    )

    $rel = $RelPath -replace "\\", "/"
    foreach ($pattern in $ExcludePatterns) {
        $pat = $pattern -replace "\\", "/"
        if ($Name -like $pat -or $rel -like $pat -or $rel.StartsWith("$pat/")) {
            return $true
        }
    }
    return $false
}

function Copy-Filtered {
    param(
        [string]$SrcDir,
        [string]$DstRoot,
        [string]$RelPrefix = ""
    )

    foreach ($Item in Get-ChildItem -LiteralPath $SrcDir -Force) {
        $RelPath = if ($RelPrefix) { "$RelPrefix/$($Item.Name)" } else { $Item.Name }

        if (Test-Excluded -Name $Item.Name -RelPath $RelPath) {
            Write-Host "  SKIP $RelPath" -ForegroundColor DarkGray
            continue
        }

        $DstPath = Join-Path $DstRoot ($RelPath -replace "/", [IO.Path]::DirectorySeparatorChar)
        if ($Item.PSIsContainer) {
            New-Item -ItemType Directory -Path $DstPath -Force | Out-Null
            Copy-Filtered -SrcDir $Item.FullName -DstRoot $DstRoot -RelPrefix $RelPath
        } else {
            $DstDir = Split-Path -Parent $DstPath
            if (-not (Test-Path $DstDir)) {
                New-Item -ItemType Directory -Path $DstDir -Force | Out-Null
            }
            Copy-Item -LiteralPath $Item.FullName -Destination $DstPath -Force
        }
    }
}

Write-Host "[PACK] Copying project files..." -ForegroundColor Cyan
Copy-Filtered -SrcDir $ProjectRoot -DstRoot $TempDir

Write-Host "[PACK] Creating archive: $PkgFile" -ForegroundColor Cyan
if (Test-Path $PkgFile) {
    Remove-Item -LiteralPath $PkgFile -Force
}
tar -czf $PkgFile -C $env:TEMP $PkgName

$Size = (Get-Item $PkgFile).Length
Write-Host "[PACK] Done. Package size: $([math]::Round($Size / 1KB, 1)) KB" -ForegroundColor Green
Write-Host "       Path: $PkgFile" -ForegroundColor Green

$PkgLeaf = Split-Path -Leaf $PkgFile
$ScpCommand = "scp `"$PkgFile`" ${ServerUser}@${ServerHost}:${RemotePath}/"
$ServerCommand = "cd $RemotePath && tar -xzf $PkgLeaf && rm -rf app && mv $PkgName app && cd app && chmod +x deploy/server_setup.sh && ./deploy/server_setup.sh"

Write-Host ""
Write-Host "Next step: upload and install" -ForegroundColor Green
Write-Host ""
Write-Host "PowerShell:"
Write-Host "  $ScpCommand" -ForegroundColor Yellow
Write-Host ""
Write-Host "SSH:"
Write-Host "  $ServerCommand" -ForegroundColor Yellow
