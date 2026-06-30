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
$refBucket = (terraform -chdir=infra/envs/dev output -raw reference_bucket_name 2>&1)
if (-not $refBucket -or $refBucket -match "Error") {
    Write-Error "Could not resolve reference_bucket_name from Terraform outputs."; exit 1
}
Write-Host "==> Uploading reference CSVs to s3://$refBucket/..." -ForegroundColor Yellow
aws s3 cp "data/users/users.csv" "s3://$refBucket/users/users.csv"
aws s3 cp "data/songs/songs.csv" "s3://$refBucket/songs/songs.csv"
Write-Host "==> Triggering dev-refresh-reference Glue job..." -ForegroundColor Yellow
$ts = [DateTimeOffset]::UtcNow.ToUnixTimeSeconds()
$jobRunId = (aws glue start-job-run --job-name "dev-refresh-reference" --arguments "--run_id=manual-$ts,--reference_bucket=$refBucket,--env=dev" --query "JobRunId" --output text)
Write-Host "    Job run started: $jobRunId"
Write-Host "==> Reference data upload complete. Parquet conversion running." -ForegroundColor Green
