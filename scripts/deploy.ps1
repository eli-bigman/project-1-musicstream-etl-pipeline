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
Write-Host "==> Resolving scripts bucket from Terraform outputs..." -ForegroundColor Yellow
$scriptsBucket = (terraform -chdir=infra/envs/dev output -raw scripts_bucket_name 2>&1)
if (-not $scriptsBucket -or $scriptsBucket -match "Error" -or $scriptsBucket -match "No outputs") {
    Write-Error "Could not read scripts_bucket_name. Did Phase 1 apply succeed?"
    exit 1
}
Write-Host "    Scripts bucket: $scriptsBucket"
Write-Host "==> Building Glue shared library wheel..." -ForegroundColor Yellow
Push-Location glue
python -m build --wheel
if ($LASTEXITCODE -ne 0) { Pop-Location; Write-Error "Wheel build failed."; exit 1 }
Pop-Location
Write-Host "==> Uploading Glue assets to S3..." -ForegroundColor Yellow
aws s3 cp "glue/dist/shared-0.1.0-py3-none-any.whl" "s3://$scriptsBucket/glue/shared/shared-0.1.0-py3-none-any.whl"
aws s3 sync "glue/pyspark/"      "s3://$scriptsBucket/glue/pyspark/"
aws s3 sync "glue/python_shell/" "s3://$scriptsBucket/glue/python_shell/"
Write-Host "==> Packaging Lambda validate_schema..." -ForegroundColor Yellow
$vsZip = "lambda\validate_schema\validate_schema.zip"
Compress-Archive -Path "lambda\validate_schema\handler.py" -DestinationPath $vsZip -Force
aws s3 cp $vsZip "s3://$scriptsBucket/lambda/0.1.0/validate_schema.zip"
Remove-Item $vsZip -Force
Write-Host "==> Packaging Lambda pipe_enrichment..." -ForegroundColor Yellow
$peZip = "lambda\pipe_enrichment\pipe_enrichment.zip"
Compress-Archive -Path "lambda\pipe_enrichment\handler.py" -DestinationPath $peZip -Force
aws s3 cp $peZip "s3://$scriptsBucket/lambda/0.1.0/pipe_enrichment.zip"
Remove-Item $peZip -Force
Write-Host "==> All assets uploaded successfully!" -ForegroundColor Green
