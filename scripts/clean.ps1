Set-StrictMode -Off
$ErrorActionPreference = "Continue"
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
Write-Host "==> Gracefully emptying S3 buckets before destroy..." -ForegroundColor Yellow
$bucketOutputs = @("raw_bucket_name","archive_bucket_name","quarantine_bucket_name","scripts_bucket_name","reference_bucket_name")
foreach ($output in $bucketOutputs) {
    $bucket = (terraform -chdir=infra/envs/dev output -raw $output 2>&1)
    if ($bucket -and $bucket -notmatch "No outputs" -and $bucket -notmatch "Error" -and $bucket -notmatch "not found") {
        Write-Host "    Emptying s3://$bucket ..."
        aws s3 rm "s3://$bucket" --recursive --only-show-errors 2>&1 | Out-Null
    }
}
Write-Host "==> Running terraform destroy..." -ForegroundColor Red
terraform -chdir=infra/envs/dev destroy -auto-approve
if ($LASTEXITCODE -ne 0) {
    Write-Warning "terraform destroy returned non-zero. Some resources may remain."
}
Write-Host "==> Cleaning local build artifacts..." -ForegroundColor Yellow
@("glue/dist","glue/build","glue/shared.egg-info",
  "lambda/validate_schema/validate_schema.zip",
  "lambda/pipe_enrichment/pipe_enrichment.zip") | ForEach-Object {
    $p = Join-Path $PSScriptRoot "..\$_"
    if (Test-Path $p) { Remove-Item $p -Recurse -Force }
}
Write-Host "==> Clean complete. Environment destroyed." -ForegroundColor Green
