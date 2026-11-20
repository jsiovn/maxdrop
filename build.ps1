# SPDX-FileCopyrightText: 2026 jsiovn
# SPDX-License-Identifier: GPL-3.0-or-later
#
# Build the MaxDrop extension zip, a static repository index and the landing page into dist\ (git-ignored).
# Usage: powershell -ExecutionPolicy Bypass -File build.ps1 [-Blender <path to blender.exe>] [-Python <python>]
# Serve dist\ over HTTP (python -m http.server --directory dist) and add its index.json in Blender as a remote
# repository to test installs and updates locally.
param(
    [string]$Blender = "C:\Program Files\Blender Foundation\Blender 5.2\blender.exe",
    [string]$Python = "python"
)
$ErrorActionPreference = "Stop"

$source = Join-Path $PSScriptRoot "maxdrop"
$dist = Join-Path $PSScriptRoot "dist"
if (-not (Test-Path $Blender)) { throw "Blender not found: $Blender (pass -Blender <path>)" }
# server-generate lists every zip in the folder, so start clean to publish one version only.
Remove-Item -Recurse -Force $dist -ErrorAction SilentlyContinue
New-Item -ItemType Directory -Force $dist | Out-Null

# Bytecode left by an in-session load would otherwise be packed into the zip.
Get-ChildItem -Path $source -Recurse -Directory -Filter "__pycache__" | Remove-Item -Recurse -Force

& $Blender --factory-startup --command extension build --source-dir $source --output-dir $dist
if ($LASTEXITCODE -ne 0) { throw "extension build failed" }

$version = (Select-String -Path (Join-Path $source "blender_manifest.toml") -Pattern '^version\s*=\s*"(.+)"').Matches[0].Groups[1].Value
$zip = Join-Path $dist "maxdrop-$version.zip"
& $Blender --factory-startup --command extension validate $zip
if ($LASTEXITCODE -ne 0) { throw "extension validate failed" }

# The GPL text travels with the add-on: maxdrop\LICENSE must be in the zip.
& $Python (Join-Path $PSScriptRoot "tools\check_zip.py") $zip
if ($LASTEXITCODE -ne 0) { throw "the zip does not carry the license text" }

# No --html: Blender's page is a bare table, ours are made from site\index.html and site\vi.html.
& $Blender --factory-startup --command extension server-generate --repo-dir $dist
if ($LASTEXITCODE -ne 0) { throw "server-generate failed" }

& $Python (Join-Path $PSScriptRoot "tools\make_site.py") $dist
if ($LASTEXITCODE -ne 0) { throw "make_site.py failed" }

Write-Host "Built $zip, $(Join-Path $dist 'index.json'), $(Join-Path $dist 'index.html') and $(Join-Path $dist 'vi.html')"
