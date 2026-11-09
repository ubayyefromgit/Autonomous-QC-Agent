$ErrorActionPreference = "Stop"
$PgBin = "C:\Program Files\PostgreSQL\18\bin"
$DataDir = Join-Path (Get-Location) ".postgres_data"
$LogFile = Join-Path (Get-Location) ".postgres_data\postgres.log"
$Port = 5433

if (-not (Test-Path "$DataDir\PG_VERSION")) {
    Write-Output "Initializing local PostgreSQL 18 cluster in $DataDir..."
    & "$PgBin\initdb.exe" -D $DataDir -U postgres -A trust -E UTF8 --no-locale
    Add-Content -Path "$DataDir\postgresql.conf" -Value "`nport = $Port`nmax_connections = 100`n"
}

$status = & "$PgBin\pg_ctl.exe" -D $DataDir status 2>&1
if ($LASTEXITCODE -ne 0) {
    Write-Output "Starting PostgreSQL 18 cluster on port $Port..."
    & "$PgBin\pg_ctl.exe" -D $DataDir -l $LogFile -o "-p $Port" start
    Start-Sleep -Seconds 2
} else {
    Write-Output "PostgreSQL 18 cluster already running on port $Port."
}

& "$PgBin\psql.exe" -h 127.0.0.1 -p $Port -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'qc_platform'" | Select-String -SimpleMatch "1" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & "$PgBin\psql.exe" -h 127.0.0.1 -p $Port -U postgres -c "CREATE DATABASE qc_platform;"
}
& "$PgBin\psql.exe" -h 127.0.0.1 -p $Port -U postgres -tc "SELECT 1 FROM pg_database WHERE datname = 'qc_platform_test'" | Select-String -SimpleMatch "1" | Out-Null
if ($LASTEXITCODE -ne 0) {
    & "$PgBin\psql.exe" -h 127.0.0.1 -p $Port -U postgres -c "CREATE DATABASE qc_platform_test;"
}
& "$PgBin\psql.exe" -h 127.0.0.1 -p $Port -U postgres -d qc_platform -c "SELECT version();"

