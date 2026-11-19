#requires -Version 7.0
[CmdletBinding(DefaultParameterSetName = "Real")]
param(
    [Parameter(Mandatory, ParameterSetName = "Sample")][switch]$Sample,
    [Parameter(Mandatory, ParameterSetName = "Real")][string]$GitHubUser,
    [Parameter(Mandatory, ParameterSetName = "Real")][string]$Enterprise,
    [string]$OutputDirectory = (Join-Path $HOME "CopilotMetricsData"),
    [Parameter(Mandatory, ParameterSetName = "Real")][string]$StartDay,
    [Parameter(Mandatory, ParameterSetName = "Real")][string]$EndDay,
    [Parameter(ParameterSetName = "Real")][switch]$AllowMissingMetrics
)

Set-StrictMode -Version Latest
$ErrorActionPreference = "Stop"

try {
    $python = $null
    $names = if ($IsWindows) { @("python", "python3") } else { @("python3", "python") }
    foreach ($name in $names) {
        $python = Get-Command $name -CommandType Application -ErrorAction SilentlyContinue | Select-Object -First 1
        if ($python) { break }
    }
    if (-not $python) {
        throw "Install Python 3.11 or newer yourself, then run this command again."
    }
    & $python.Source -c "import sys; sys.exit(0 if sys.version_info >= (3, 11) else 1)"
    if ($LASTEXITCODE -ne 0) {
        throw "Python 3.11 or newer is required."
    }
    if (-not $Sample -and -not (Get-Command gh -CommandType Application -ErrorAction SilentlyContinue)) {
        throw "Install GitHub CLI and sign in yourself using the documented scopes."
    }
    $arguments = @((Join-Path $PSScriptRoot "download_local.py"), "--output-directory", $OutputDirectory)
    if ($Sample) {
        $arguments += "--sample"
    } else {
        $arguments += @("--github-user", $GitHubUser, "--enterprise", $Enterprise,
                        "--start-day", $StartDay, "--end-day", $EndDay)
        if ($AllowMissingMetrics) { $arguments += "--allow-missing-metrics" }
    }
    & $python.Source @arguments
    exit $LASTEXITCODE
} catch {
    Write-Error -Message $_.Exception.Message -ErrorAction Continue
    exit 1
}
