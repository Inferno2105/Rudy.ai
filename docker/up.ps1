# Build (if needed) and start RuDy.ai in Docker.
#
#   powershell -File docker/up.ps1            # build + start in the background
#   powershell -File docker/up.ps1 -Rebuild   # force a fresh build of the app image
#
# Records the current git commit (and whether there are uncommitted changes)
# into the image, so every run made in the container stays traceable to the
# exact code that produced it.
param([switch]$Rebuild)

$ErrorActionPreference = 'Stop'
Set-Location (Join-Path $PSScriptRoot '..')

$env:GIT_COMMIT = (git rev-parse HEAD).Trim()
$env:GIT_BRANCH = (git rev-parse --abbrev-ref HEAD).Trim()
$env:GIT_DIRTY = if (git status --porcelain) { 'true' } else { 'false' }
# The host's UTC offset as a POSIX TZ string (no zoneinfo needed in the image),
# so runs made in the container are stamped with the same clock as native ones.
# POSIX counts the other way: UTC+05:30 is written <+0530>-05:30.
$offset = [TimeZoneInfo]::Local.GetUtcOffset([DateTime]::Now)
$abs = $offset.Duration()
$east = $offset -ge [TimeSpan]::Zero
$env:CONTAINER_TZ = '<{0}{1:hh}{1:mm}>{2}{1:hh}:{1:mm}' -f $(if ($east) { '+' } else { '-' }), $abs, $(if ($east) { '-' } else { '+' })

if (-not (Test-Path .env)) {
    Write-Warning '.env not found: diarization needs HF_TOKEN. Copy .env.example to .env and fill it in.'
}

Write-Host "Building from commit $($env:GIT_COMMIT.Substring(0, 7)) (dirty: $env:GIT_DIRTY)"
$buildArgs = @('compose', 'build')
if ($Rebuild) { $buildArgs += '--no-cache' }
& docker @buildArgs app
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

& docker compose up -d
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

Write-Host ''
Write-Host 'Starting. The first start downloads the language models (~10 GB) and,'
Write-Host 'on the first meeting, the speech models (~3 GB); later starts are quick.'
Write-Host 'Open http://127.0.0.1:8000/   (logs: docker compose logs -f app)'
