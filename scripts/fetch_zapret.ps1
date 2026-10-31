$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
$version = '1.10.4'
$expected = '291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34'
$archive = Join-Path (Get-Location) "vendor/zapret-$version.zip"
New-Item -ItemType Directory -Path 'vendor' -Force | Out-Null
if (-not (Test-Path -LiteralPath $archive)) {
    Invoke-WebRequest "https://github.com/Flowseal/zapret-discord-youtube/releases/download/$version/zapret-discord-youtube-$version.zip" -OutFile $archive -UseBasicParsing
}
if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected) {
    throw 'Zapret checksum mismatch; refusing to unpack.'
}
Expand-Archive -LiteralPath $archive -DestinationPath 'vendor/zapret' -Force
Write-Host 'Verified clean upstream Zapret bundle. No local user lists were copied.'
