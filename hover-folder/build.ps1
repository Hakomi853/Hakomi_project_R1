Set-StrictMode -Version Latest
$ErrorActionPreference = 'Stop'

$framework = Join-Path $env:WINDIR 'Microsoft.NET\Framework64\v4.0.30319'
$compiler = Join-Path $framework 'csc.exe'
if (!(Test-Path -LiteralPath $compiler)) {
    throw "The .NET Framework C# compiler was not found at $compiler."
}

$references = @('PresentationCore', 'PresentationFramework', 'WindowsBase', 'UIAutomationClient', 'UIAutomationTypes') | ForEach-Object {
    '/r:' + (Join-Path $framework "WPF\$_.dll")
}
$sources = @('Desktop.cs', 'Integration.cs', 'ManagerStyles.cs', 'PreviewDrag.cs') | ForEach-Object {
    Join-Path $PSScriptRoot "src\$_"
}
$dist = Join-Path $PSScriptRoot 'dist'
New-Item -Path $dist -ItemType Directory -Force | Out-Null
$output = Join-Path $dist '悬浮文件夹.exe'
$icon = Join-Path $PSScriptRoot 'assets\manager.ico'
& $compiler /nologo /target:winexe /optimize+ /r:Accessibility.dll /r:System.Xaml.dll /r:Microsoft.CSharp.dll @references "/win32icon:$icon" "/out:$output" @sources
if ($LASTEXITCODE -ne 0) {
    throw "Build failed with exit code $LASTEXITCODE."
}
Write-Output $output
