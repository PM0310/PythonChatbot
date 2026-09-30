# Oracle Wallet Management Script
# Run this to extract, configure, and test your Oracle Wallet

param(
    [string]$WalletZipPath = "",
    [string]$WalletDestination = "C:\oracle\wallet",
    [string]$Action = "setup"
)

# Color output
function Write-Success { Write-Host $args -ForegroundColor Green }
function Write-Error-Custom { Write-Host $args -ForegroundColor Red }
function Write-Info { Write-Host $args -ForegroundColor Cyan }
function Write-Warning-Custom { Write-Host $args -ForegroundColor Yellow }

# ============================================================================
# MAIN MENU
# ============================================================================

if ($Action -eq "menu" -or -not $Action) {
    Clear-Host
    Write-Info "=========================================="
    Write-Info "  ORACLE WALLET MANAGEMENT TOOL"
    Write-Info "=========================================="
    Write-Info ""
    Write-Info "Select an option:"
    Write-Info "1. Extract wallet from ZIP"
    Write-Info "2. View wallet details"
    Write-Info "3. Test database connection"
    Write-Info "4. Set environment variables"
    Write-Info "5. Find wallet on system"
    Write-Info "6. Create config file"
    Write-Info "0. Exit"
    Write-Info ""
    
    $choice = Read-Host "Enter your choice (0-6)"
    
    switch ($choice) {
        "1" { Extract-Wallet }
        "2" { View-Wallet-Details }
        "3" { Test-Connection }
        "4" { Set-Environment-Variables }
        "5" { Find-Wallet }
        "6" { Create-Config-File }
        "0" { exit }
        default { Write-Error-Custom "Invalid choice"; exit }
    }
}

# ============================================================================
# FUNCTION: Extract Wallet
# ============================================================================

function Extract-Wallet {
    Write-Info "`n=== EXTRACT WALLET FROM ZIP ===="
    
    # Get wallet ZIP path if not provided
    if (-not $WalletZipPath) {
        Write-Info "Enter the full path to your Wallet ZIP file:"
        Write-Info "Example: C:\Downloads\Wallet_ADW4Workshops.zip"
        $WalletZipPath = Read-Host "Wallet ZIP path"
    }
    
    # Validate ZIP exists
    if (-not (Test-Path $WalletZipPath)) {
        Write-Error-Custom "ERROR: Wallet ZIP file not found: $WalletZipPath"
        return
    }
    
    # Create destination directory
    if (-not (Test-Path $WalletDestination)) {
        Write-Info "Creating wallet directory: $WalletDestination"
        New-Item -ItemType Directory -Path $WalletDestination -Force | Out-Null
    }
    
    # Extract wallet
    try {
        Write-Info "Extracting wallet..."
        Expand-Archive -Path $WalletZipPath -DestinationPath $WalletDestination -Force
        Write-Success "✓ Wallet extracted successfully!"
    } catch {
        Write-Error-Custom "✗ Error extracting wallet: $_"
        return
    }
    
    # Verify extraction
    $walletFiles = @("cwallet.sso", "ewallet.p12", "tnsnames.ora", "sqlnet.ora")
    Write-Info "`nVerifying wallet files..."
    
    $allFilesFound = $true
    foreach ($file in $walletFiles) {
        $filePath = Join-Path $WalletDestination $file
        if (Test-Path $filePath) {
            Write-Success "  ✓ $file"
        } else {
            Write-Error-Custom "  ✗ Missing: $file"
            $allFilesFound = $false
        }
    }
    
    if ($allFilesFound) {
        Write-Success "`n✓ All required wallet files found!"
    } else {
        Write-Error-Custom "`n✗ Some wallet files are missing. Please check the ZIP file."
    }
    
    # Display next steps
    Write-Info "`nNext steps:"
    Write-Info "1. Run option 2 to view wallet details"
    Write-Info "2. Run option 4 to set environment variables"
    Write-Info "3. Run option 3 to test connection"
}

# ============================================================================
# FUNCTION: View Wallet Details
# ============================================================================

function View-Wallet-Details {
    Write-Info "`n=== WALLET DETAILS ===="
    
    if (-not (Test-Path $WalletDestination)) {
        Write-Error-Custom "ERROR: Wallet directory not found: $WalletDestination"
        Write-Info "Please run option 1 to extract wallet first."
        return
    }
    
    # List files
    Write-Info "`nWallet Files:"
    Get-ChildItem $WalletDestination | ForEach-Object {
        $size = if ($_.PSIsContainer) { "-" } else { "$($_.Length) bytes" }
        Write-Info "  ✓ $($_.Name) ($size)"
    }
    
    # Read README
    $readmeFile = Join-Path $WalletDestination "README.txt"
    if (Test-Path $readmeFile) {
        Write-Info "`n=== README.TXT CONTENTS ===="
        $content = Get-Content $readmeFile
        Write-Host $content
    }
    
    # Read tnsnames.ora
    $tnsFile = Join-Path $WalletDestination "tnsnames.ora"
    if (Test-Path $tnsFile) {
        Write-Info "`n=== TNSNAMES.ORA (Connection Strings) ===="
        $content = Get-Content $tnsFile
        # Show first 500 characters
        Write-Host ($content | Select-Object -First 20 | Out-String)
        Write-Info "[... truncated for brevity]"
    }
    
    # Read sqlnet.ora
    $sqlnetFile = Join-Path $WalletDestination "sqlnet.ora"
    if (Test-Path $sqlnetFile) {
        Write-Info "`n=== SQLNET.ORA (Configuration) ===="
        Get-Content $sqlnetFile
    }
}

# ============================================================================
# FUNCTION: Test Database Connection
# ============================================================================

function Test-Connection {
    Write-Info "`n=== TEST DATABASE CONNECTION ===="
    
    # Check if wallet exists
    if (-not (Test-Path $WalletDestination)) {
        Write-Error-Custom "ERROR: Wallet directory not found"
        return
    }
    
    # Set environment variable
    $env:TNS_ADMIN = $WalletDestination
    Write-Info "Set TNS_ADMIN = $WalletDestination"
    
    # Check for sqlplus
    $sqlplus = Get-Command sqlplus -ErrorAction SilentlyContinue
    if ($sqlplus) {
        Write-Info "`nFound SQL*Plus at: $($sqlplus.Source)"
        Write-Info "`nTo test connection, run:"
        Write-Info "  sqlplus admin@adwc_low"
        Write-Info "`nEnter your password when prompted."
    } else {
        Write-Warning-Custom "SQL*Plus not found. Checking for SQLcl..."
    }
    
    # Check for sqlcl
    $sqlcl = Get-Command sql -ErrorAction SilentlyContinue
    if ($sqlcl) {
        Write-Info "`nFound SQLcl at: $($sqlcl.Source)"
        Write-Info "`nTo test connection, run:"
        Write-Info "  sql admin@adwc_low"
        Write-Info "`nEnter your password when prompted."
    } else {
        Write-Warning-Custom "`nNeither SQL*Plus nor SQLcl found on PATH"
        Write-Info "Install Oracle SQL Developer Command Line or SQL*Plus to test connections"
    }
    
    # Parse tnsnames.ora for available services
    $tnsFile = Join-Path $WalletDestination "tnsnames.ora"
    if (Test-Path $tnsFile) {
        Write-Info "`nAvailable service names in wallet:"
        $content = Get-Content $tnsFile
        $services = $content | Select-String "^\w+\s*=" | ForEach-Object {
            $_.Line -replace "^\s*(\w+)\s*=.*", '$1'
        }
        $services | ForEach-Object {
            Write-Info "  • $_"
        }
    }
}

# ============================================================================
# FUNCTION: Set Environment Variables
# ============================================================================

function Set-Environment-Variables {
    Write-Info "`n=== SET ENVIRONMENT VARIABLES ===="
    
    if (-not (Test-Path $WalletDestination)) {
        Write-Error-Custom "ERROR: Wallet directory not found"
        Write-Info "Please extract wallet first."
        return
    }
    
    Write-Info "Setting permanent environment variables..."
    
    try {
        # Set TNS_ADMIN
        [Environment]::SetEnvironmentVariable(
            "TNS_ADMIN",
            $WalletDestination,
            [EnvironmentVariableTarget]::User
        )
        Write-Success "✓ TNS_ADMIN set to: $WalletDestination"
        
        # Set current session
        $env:TNS_ADMIN = $WalletDestination
        
        Write-Info "`nEnvironment Variables Set:"
        Write-Info "  TNS_ADMIN = $env:TNS_ADMIN"
        
        Write-Success "`n✓ Changes will take effect in new PowerShell windows"
    } catch {
        Write-Error-Custom "✗ Error setting environment variables: $_"
    }
}

# ============================================================================
# FUNCTION: Find Wallet on System
# ============================================================================

function Find-Wallet {
    Write-Info "`n=== SEARCHING FOR WALLET FILES ===="
    Write-Info "This may take a few moments..."
    
    $walletFiles = Get-ChildItem -Path "C:\" -Filter "*wallet*" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 20
    $walletZips = Get-ChildItem -Path "C:\" -Filter "*Wallet*.zip" -Recurse -ErrorAction SilentlyContinue | Select-Object -First 10
    
    if ($walletZips) {
        Write-Success "`nWallet ZIP files found:"
        $walletZips | ForEach-Object {
            Write-Info "  • $($_.FullName) ($('{0:N0}' -f $_.Length) bytes)"
        }
    }
    
    if ($walletFiles) {
        Write-Success "`nWallet-related files found:"
        $walletFiles | Select-Object -First 10 | ForEach-Object {
            Write-Info "  • $($_.FullName)"
        }
    }
    
    if (-not $walletZips -and -not $walletFiles) {
        Write-Error-Custom "No wallet files found on C:\ drive"
        Write-Info "`nPlease:"
        Write-Info "1. Download wallet from Oracle Cloud APEX"
        Write-Info "2. Save it locally"
        Write-Info "3. Run option 1 to extract it"
    }
}

# ============================================================================
# FUNCTION: Create Config File
# ============================================================================

function Create-Config-File {
    Write-Info "`n=== CREATE CONFIGURATION FILE ===="
    
    if (-not (Test-Path $WalletDestination)) {
        Write-Error-Custom "ERROR: Wallet directory not found"
        return
    }
    
    # Parse tnsnames.ora
    $tnsFile = Join-Path $WalletDestination "tnsnames.ora"
    $services = @()
    if (Test-Path $tnsFile) {
        $content = Get-Content $tnsFile
        $services = $content | Select-String "^\w+\s*=" | ForEach-Object {
            $_.Line -replace "^\s*(\w+)\s*=.*", '$1'
        }
    }
    
    # Create config
    $configPath = "C:\oracle\wallet\wallet_config.json"
    
    $config = @{
        wallet_location = $WalletDestination
        tns_admin = $WalletDestination
        database = @{
            user = "admin"
            default_service = if ($services) { $services[0] } else { "adwc_low" }
            available_services = $services
        }
        environment = @{
            TNS_ADMIN = $WalletDestination
            ORACLE_HOME = "C:\oracle\client"
        }
    }
    
    $config | ConvertTo-Json | Out-File -FilePath $configPath -Encoding UTF8
    
    Write-Success "✓ Configuration file created: $configPath"
    Write-Info "`nContents:"
    Get-Content $configPath
    
    Write-Info "`n✓ You can now use this config with your Python or APEX applications"
}

# ============================================================================
# RUN DEFAULT MENU
# ============================================================================

if ($WalletZipPath -and $Action -eq "setup") {
    Extract-Wallet
} else {
    # Show interactive menu
    & "$PSScriptRoot\$($MyInvocation.MyCommand.Name)" -Action "menu"
}
