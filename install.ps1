# Bootstrap for the public, reviewed Windows x64 release. No elevation required.
& {
    $ErrorActionPreference = 'Stop'
    if ($env:OS -ne 'Windows_NT' -or -not [Environment]::Is64BitOperatingSystem) {
        throw 'This release requires 64-bit Windows.'
    }
    if ($env:PROCESSOR_ARCHITECTURE -eq 'ARM64' -or $env:PROCESSOR_ARCHITEW6432 -eq 'ARM64') {
        throw 'ARM64 is not supported by this release.'
    }
    [Net.ServicePointManager]::SecurityProtocol = [Net.SecurityProtocolType]::Tls12
    $repository = 'Ixtron/youtube-mp3-studio'
    $base = Join-Path $env:LOCALAPPDATA 'YouTubeMP3'
    $headers = @{ 'User-Agent' = 'YouTubeMP3-Installer'; Accept = 'application/vnd.github+json' }
    $release = Invoke-RestMethod "https://raw.githubusercontent.com/$repository/main/release.json" -Headers $headers
    if ($release.tag_name -notmatch '^v\d+\.\d+\.\d+(-preview\.\d+)?$') { throw 'Invalid release version.' }
    $assetName = 'YouTubeMP3-windows-x64.zip'
    $zipAsset = @($release.assets | Where-Object name -eq $assetName)
    $hashAsset = @($release.assets | Where-Object name -eq 'SHA256SUMS.txt')
    if ($zipAsset.Count -ne 1 -or $hashAsset.Count -ne 1) { throw 'Release assets are incomplete.' }
    foreach ($asset in @($zipAsset[0], $hashAsset[0])) {
        if (-not $asset.browser_download_url.StartsWith("https://github.com/$repository/releases/download/")) {
            throw 'Unexpected download URL.'
        }
    }
    $versionDir = Join-Path (Join-Path $base 'versions') $release.tag_name
    $executable = Join-Path $versionDir 'YouTubeMP3.exe'
    if (-not (Test-Path -LiteralPath (Join-Path $versionDir '.verified'))) {
        $staging = Join-Path $base ('staging-' + [Guid]::NewGuid().ToString('N'))
        New-Item -ItemType Directory -Path $staging -Force | Out-Null
        try {
            $archive = Join-Path $staging $assetName
            Invoke-WebRequest $zipAsset[0].browser_download_url -OutFile $archive -UseBasicParsing
            $hashes = Invoke-RestMethod $hashAsset[0].browser_download_url
            $expected = [regex]::Match([string]$hashes, '(?m)^([a-fA-F0-9]{64})\s+\*?YouTubeMP3-windows-x64\.zip\s*$')
            if (-not $expected.Success) { throw 'Release checksum missing.' }
            if ((Get-FileHash -LiteralPath $archive -Algorithm SHA256).Hash -ne $expected.Groups[1].Value) {
                throw 'Checksum mismatch. Nothing was launched.'
            }
            $unpacked = Join-Path $staging 'unpacked'
            Expand-Archive -LiteralPath $archive -DestinationPath $unpacked
            function Get-VerifiedComponent($Url, $Hash, $Name) {
                $destination = Join-Path $staging $Name
                Write-Host "Downloading $Name ..."
                Invoke-WebRequest $Url -OutFile $destination -UseBasicParsing
                if ((Get-FileHash -LiteralPath $destination -Algorithm SHA256).Hash -ne $Hash) {
                    throw "Component checksum mismatch: $Name. Nothing was launched."
                }
                return $destination
            }
            if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'node.exe'))) {
                $node = Get-VerifiedComponent 'https://nodejs.org/dist/v25.5.0/win-x64/node.exe' 'd7f55cbc1b1ca9cc2815d7b8c58f94e4822a68cdf5ca55b4f2c9625581b92839' 'node.exe'
                Copy-Item -LiteralPath $node -Destination $unpacked
            }
            if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'ffmpeg.exe')) -or -not (Test-Path -LiteralPath (Join-Path $unpacked 'ffprobe.exe'))) {
                $ffmpeg = Get-VerifiedComponent 'https://github.com/GyanD/codexffmpeg/releases/download/2026-03-05-git-74cfcd1c69/ffmpeg-2026-03-05-git-74cfcd1c69-full_build.zip' '7df56acc4432fa2a40469ad013476a6f95d518dc0e50593e5970dd0d9ff31c8e' 'ffmpeg.zip'
                $ffmpegStage = Join-Path $staging 'ffmpeg'
                Expand-Archive -LiteralPath $ffmpeg -DestinationPath $ffmpegStage
                $ffmpegRoot = Join-Path $ffmpegStage 'ffmpeg-2026-03-05-git-74cfcd1c69-full_build'
                Copy-Item -LiteralPath (Join-Path $ffmpegRoot 'bin/ffmpeg.exe'), (Join-Path $ffmpegRoot 'bin/ffprobe.exe') -Destination $unpacked
                $ffmpegLicense = Join-Path $unpacked 'licenses/ffmpeg'
                New-Item -ItemType Directory -Path $ffmpegLicense -Force | Out-Null
                Copy-Item -LiteralPath (Join-Path $ffmpegRoot 'LICENSE'), (Join-Path $ffmpegRoot 'README.txt') -Destination $ffmpegLicense
            }
            if (-not (Test-Path -LiteralPath (Join-Path $unpacked 'zapret/service.bat'))) {
                $zapret = Get-VerifiedComponent 'https://github.com/Flowseal/zapret-discord-youtube/releases/download/1.10.4/zapret-discord-youtube-1.10.4.zip' '291af673bd0238506f9548e0e94ca0abf244000f4c9a06960544fb01c5f97b34' 'zapret.zip'
                $zapretStage = Join-Path $staging 'zapret'
                Expand-Archive -LiteralPath $zapret -DestinationPath $zapretStage
                Copy-Item -LiteralPath (Join-Path $zapretStage 'zapret-discord-youtube-1.10.4') -Destination (Join-Path $unpacked 'zapret') -Recurse
            }
            foreach ($name in @('YouTubeMP3.exe', 'ffmpeg.exe', 'ffprobe.exe', 'node.exe', 'LoginHelper.exe')) {
                if (-not (Test-Path -LiteralPath (Join-Path $unpacked $name))) { throw "Missing $name" }
            }
            if (Test-Path -LiteralPath $versionDir) { throw 'Incomplete installation exists; inspect the version folder.' }
            New-Item -ItemType Directory -Path (Split-Path $versionDir -Parent) -Force | Out-Null
            Move-Item -LiteralPath $unpacked -Destination $versionDir
            Set-Content -LiteralPath (Join-Path $versionDir '.verified') -Value $expected.Groups[1].Value
        } finally {
            $resolvedBase = [IO.Path]::GetFullPath($base).TrimEnd('\') + '\'
            $resolvedStaging = [IO.Path]::GetFullPath($staging)
            if ($resolvedStaging.StartsWith($resolvedBase, [StringComparison]::OrdinalIgnoreCase)) {
                Remove-Item -LiteralPath $resolvedStaging -Recurse -Force
            }
        }
    }
    if (-not (Test-Path -LiteralPath $executable)) { throw 'Installed application is missing.' }
    Start-Process -FilePath $executable -WorkingDirectory $versionDir -WindowStyle Hidden
}
