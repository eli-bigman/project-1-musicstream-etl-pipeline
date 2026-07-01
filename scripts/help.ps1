$ESC = [char]27
$R   = "$ESC[0m"

# Color palette
$CYAN   = "$ESC[96m"
$BLUE   = "$ESC[94m"
$GREEN  = "$ESC[92m"
$YELLOW = "$ESC[93m"
$RED    = "$ESC[91m"
$GRAY   = "$ESC[90m"
$WHITE  = "$ESC[97m"
$BOLD   = "$ESC[1m"
$DIM    = "$ESC[2m"

function Pad($s, $n) { $s.PadRight($n) }

$width = 62

# -- Banner ------------------------------------------------------------------
Write-Host ""
Write-Host "$CYAN$BOLD  +-----------------------------------------------------------------+$R"
Write-Host "$CYAN$BOLD  |                                                                 |$R"
Write-Host "$CYAN$BOLD  |    $WHITE  M U S I C S T R E A M   E T L   P I P E L I N E$CYAN$BOLD        |$R"
Write-Host "$CYAN$BOLD  |    $DIM$GRAY  AWS S3 + Glue + Step Functions + DynamoDB + Lambda  $R$CYAN$BOLD  |$R"
Write-Host "$CYAN$BOLD  |                                                                 |$R"
Write-Host "$CYAN$BOLD  +-----------------------------------------------------------------+$R"
Write-Host ""

# -- Environment snapshot ----------------------------------------------------
$env_val = if ($env:TF_VAR_environment) { $env:TF_VAR_environment } else { "dev" }
$region  = if ($env:AWS_DEFAULT_REGION)  { $env:AWS_DEFAULT_REGION  } else { "eu-west-1" }

Write-Host "  $DIM$GRAY  Environment:$R $GREEN$env_val$R   $DIM$GRAY Region:$R $YELLOW$region$R"
Write-Host ""

# -- Section: Lifecycle -------------------------------------------------------
Write-Host "  $BOLD$BLUE  LIFECYCLE$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host "  $GRAY  | $R$YELLOW$(Pad 'make clean' 14)$GRAY  | $R$(Pad 'Destroy all AWS resources + clean local artifacts' 41)$GRAY  |$R"
Write-Host "  $GRAY  | $R$GREEN$(Pad 'make deploy' 14)$GRAY  | $R$(Pad 'Full deploy (infra, code assets, & reference data)' 41)$GRAY  |$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host ""

# -- Section: Data ------------------------------------------------------------
Write-Host "  $BOLD$BLUE  DATA$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host "  $GRAY  | $R$CYAN$(Pad 'make upload' 14)$GRAY  | $R$(Pad 'Sync reference CSVs (users, songs) & run Glue job' 41)$GRAY  |$R"
Write-Host "  $GRAY  | $R$CYAN$(Pad 'make seed-data' 14)$GRAY  | $R$(Pad 'Push sample stream CSVs to raw S3 to trigger ETL' 41)$GRAY  |$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host ""

# -- Section: Dev -------------------------------------------------------------
Write-Host "  $BOLD$BLUE  DEVELOPMENT$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host "  $GRAY  | $R$WHITE$(Pad 'make ui' 14)$GRAY  | $R$(Pad 'Launch Streamlit KPI dashboard  :8501' 41)$GRAY  |$R"
Write-Host "  $GRAY  | $R$WHITE$(Pad 'make test' 14)$GRAY  | $R$(Pad 'Run unit + integration test suite' 41)$GRAY  |$R"
Write-Host "  $GRAY  | $R$WHITE$(Pad 'make upload-assets' 14)$GRAY  | $R$(Pad 'Re-upload Glue/Lambda code (no full redeploy)' 41)$GRAY  |$R"
Write-Host "  $GRAY  +----------------+-------------------------------------------+$R"
Write-Host ""

# -- Tip ---------------------------------------------------------------------
Write-Host "  $DIM$GRAY  Demo flow:  make clean  ->  make deploy  ->  make seed-data  ->  make ui$R"
Write-Host ""
