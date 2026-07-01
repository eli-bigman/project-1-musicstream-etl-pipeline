param([Parameter(ValueFromRemainingArguments=$true)][string[]]$Command)
Set-StrictMode -Off
$ErrorActionPreference = "Stop"
$envFile = Join-Path $PSScriptRoot "..\.env"
if (Test-Path $envFile) {
    Get-Content $envFile | ForEach-Object {
        $line = $_.Trim()
        if ($line -and -not $line.StartsWith("#") -and $line.Contains("=")) {
            $name, $val = $line -split "=", 2
            $name = $name.Trim(); $val = $val.Trim()
            [System.Environment]::SetEnvironmentVariable($name, $val)
            Set-Content "env:\$name" $val -ErrorAction SilentlyContinue
        }
    }
}
if ($Command.Count -gt 0) {
    $exe  = $Command[0]
    $rest = $Command[1..($Command.Count - 1)]
    & $exe @rest
    exit $LASTEXITCODE
}
