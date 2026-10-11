# Build paper/main.pdf.
#
#   powershell -File paper/build.ps1           # build once
#   powershell -File paper/build.ps1 -Final    # submission.pdf; fails on any placeholder
#
# Uses a local latexmk if one is installed (MiKTeX or TeX Live). Otherwise it
# uses Docker: the first run builds a small local image, TeX Live plus the few
# packages the IEEE template needs (a few minutes, once); later runs only
# compile.
param([switch]$Final)

$ErrorActionPreference = 'Stop'
Set-Location $PSScriptRoot

# -Final defines \SUBMISSION before main.tex, which turns placeholders into errors.
$latexArgs = @('-pdf', '-interaction=nonstopmode', '-halt-on-error')
# The submission build writes submission.pdf with its own bookkeeping files, so
# it never reuses (or disturbs) the draft; -g forces a full rebuild every time.
if ($Final) { $latexArgs += @('-g', '-jobname=submission', '-usepretex=\def\SUBMISSION{}') }

if (Get-Command latexmk -ErrorAction SilentlyContinue) {
    & latexmk @latexArgs main.tex
    exit $LASTEXITCODE
}

$image = 'meeting-assistant-latex'
# `docker images -q` prints nothing (and no error) when the image is missing.
if (-not (& docker images -q $image)) {
    Write-Host "Building the $image image (once)..."
    # A pinned mirror: a randomly chosen one that lags behind makes tlmgr
    # refuse to install anything.
    @'
FROM texlive/texlive:latest-small
RUN tlmgr --repository https://ftp.fau.de/ctan/systems/texlive/tlnet install \
      ieeetran pgf multirow booktabs cite latexmk courier times helvetic psnfss
'@ | docker build -t $image -
    if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }
}

& docker run --rm -v "${PWD}:/paper" -w /paper $image latexmk @latexArgs main.tex
exit $LASTEXITCODE
