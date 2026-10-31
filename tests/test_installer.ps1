$ErrorActionPreference = 'Stop'
$originalData = $env:LOCALAPPDATA
$testRoot = Join-Path ([IO.Path]::GetTempPath()) ('youtube-installer-test-' + [Guid]::NewGuid().ToString('N'))
New-Item -ItemType Directory -Path $testRoot | Out-Null
$env:LOCALAPPDATA = $testRoot
$global:youtubeInstallerTest_launches = 0
$global:youtubeInstallerTest_downloads = 0
$global:youtubeInstallerTest_corrupt = $false
$global:youtubeInstallerTest_tag = 'v4.0.0'
$source = Join-Path $testRoot 'payload'
New-Item -ItemType Directory -Path $source | Out-Null
foreach ($name in @('YouTubeMP3.exe', 'LoginHelper.exe', 'ffmpeg.exe', 'ffprobe.exe', 'node.exe')) {
    Set-Content -LiteralPath (Join-Path $source $name) -Value 'TEST FIXTURE - NOT EXECUTABLE'
}
New-Item -ItemType Directory -Path (Join-Path $source 'zapret') | Out-Null
Set-Content -LiteralPath (Join-Path $source 'zapret/service.bat') -Value 'TEST FIXTURE'
$global:youtubeInstallerTest_fixture = Join-Path $testRoot 'fixture.zip'
Compress-Archive -Path (Join-Path $source '*') -DestinationPath $global:youtubeInstallerTest_fixture
$global:youtubeInstallerTest_hash = (Get-FileHash -LiteralPath $global:youtubeInstallerTest_fixture -Algorithm SHA256).Hash
function Invoke-RestMethod {
    param($Uri, $Headers)
    if ($Uri -like '*/release.json') {
        return @{ tag_name = $global:youtubeInstallerTest_tag; assets = @(
            @{ name='YouTubeMP3-windows-x64.zip'; browser_download_url='https://github.com/Ixtron/youtube-mp3-studio/releases/download/test/archive.zip' },
            @{ name='SHA256SUMS.txt'; browser_download_url='https://github.com/Ixtron/youtube-mp3-studio/releases/download/test/SHA256SUMS.txt' }
        ) }
    }
    if ($global:youtubeInstallerTest_corrupt) { return (('0' * 64) + '  YouTubeMP3-windows-x64.zip') }
    return ($global:youtubeInstallerTest_hash + '  YouTubeMP3-windows-x64.zip')
}
function Invoke-WebRequest {
    param($Uri, $OutFile, [switch]$UseBasicParsing)
    $global:youtubeInstallerTest_downloads++
    Copy-Item -LiteralPath $global:youtubeInstallerTest_fixture -Destination $OutFile
}
function Start-Process {
    param($FilePath, $WorkingDirectory, $WindowStyle)
    if (-not (Test-Path -LiteralPath $FilePath)) { throw 'Missing application' }
    $global:youtubeInstallerTest_launches++
}
try {
    $installer = Join-Path (Split-Path $PSScriptRoot -Parent) 'install.ps1'
    $privateData = Join-Path $testRoot 'YouTubeMP3/data'
    New-Item -ItemType Directory -Path $privateData -Force | Out-Null
    $sentinel = Join-Path $privateData 'sentinel.txt'
    Set-Content -LiteralPath $sentinel -Value 'PRIVATE TEST DATA'
    & $installer
    if ($global:youtubeInstallerTest_launches -ne 1) { throw 'First launch failed' }
    & $installer
    if ($global:youtubeInstallerTest_launches -ne 2 -or $global:youtubeInstallerTest_downloads -ne 1) { throw 'Cached launch failed' }
    $global:youtubeInstallerTest_corrupt = $true
    $global:youtubeInstallerTest_tag = 'v4.0.1'
    $rejected = $false
    try { & $installer } catch { $rejected = $_.Exception.Message -like '*Checksum mismatch*' }
    if (-not $rejected -or $global:youtubeInstallerTest_launches -ne 2) { throw 'Invalid checksum was not rejected' }
    if ((Get-Content -LiteralPath $sentinel) -ne 'PRIVATE TEST DATA') { throw 'Private data modified' }
    Write-Host 'PASS: first install, cached launch, checksum rejection, private data preservation.'
} finally {
    $env:LOCALAPPDATA = $originalData
    $resolved = [IO.Path]::GetFullPath($testRoot)
    $tempRoot = [IO.Path]::GetFullPath([IO.Path]::GetTempPath()).TrimEnd('\') + '\'
    if ($resolved.StartsWith($tempRoot, [StringComparison]::OrdinalIgnoreCase) -and (Split-Path $resolved -Leaf) -like 'youtube-installer-test-*') {
        Remove-Item -LiteralPath $resolved -Recurse -Force
    }
}
