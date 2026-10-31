$ErrorActionPreference = 'Stop'
Set-Location (Split-Path $PSScriptRoot -Parent)
foreach ($name in @('ffmpeg.exe', 'ffprobe.exe', 'node.exe')) {
    if (-not (Test-Path -LiteralPath (Join-Path 'vendor' $name))) { throw "Missing vendor/$name" }
}
$zapretArchive = Join-Path (Get-Location) 'vendor/zapret-1.10.4.zip'
if (-not (Test-Path -LiteralPath $zapretArchive)) { throw 'Run scripts/fetch_zapret.ps1 first.' }
if ((Get-FileHash -LiteralPath $zapretArchive -Algorithm SHA256).Hash -ne '291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34') {
    throw 'Zapret archive checksum mismatch.'
}
python -m unittest discover -s tests -v
if ($LASTEXITCODE -ne 0) { throw 'Tests failed' }
python -m PyInstaller --noconfirm --windowed --onedir --name YouTubeMP3 --collect-all customtkinter --collect-all yt_dlp_ejs --exclude-module torch --exclude-module matplotlib --exclude-module scipy --exclude-module pandas --exclude-module numpy app.py
if ($LASTEXITCODE -ne 0) { throw 'Application build failed' }
python -m PyInstaller --noconfirm --console --onedir --name LoginHelper --collect-all webview --exclude-module torch --exclude-module matplotlib --exclude-module scipy --exclude-module pandas --exclude-module numpy login_helper.py
if ($LASTEXITCODE -ne 0) { throw 'Login helper build failed' }
Copy-Item -LiteralPath 'dist/LoginHelper/LoginHelper.exe' -Destination 'dist/YouTubeMP3'
Copy-Item -Path 'dist/LoginHelper/_internal/*' -Destination 'dist/YouTubeMP3/_internal' -Recurse -Force
foreach ($name in @('ffmpeg.exe', 'ffprobe.exe', 'node.exe')) {
    Copy-Item -LiteralPath (Join-Path 'vendor' $name) -Destination 'dist/YouTubeMP3'
}
# Always unpack a fresh verified archive. Never distribute a used local profile folder.
$zapretStage = Join-Path (Get-Location) ('build/zapret-' + [Guid]::NewGuid().ToString('N'))
Expand-Archive -LiteralPath $zapretArchive -DestinationPath $zapretStage
Copy-Item -LiteralPath (Join-Path $zapretStage 'zapret-discord-youtube-1.10.4') -Destination 'dist/YouTubeMP3/zapret' -Recurse
Write-Host 'Local preview built: dist/YouTubeMP3/YouTubeMP3.exe'
Write-Host 'Before public distribution, include third-party licenses and corresponding source notices.'
