param(
    [string]$FinTraceDataset = "datasets\fintrace-redteam-v1",
    [string]$RedAttackDataset = "datasets\red_attack_v1",
    [string]$ShowcaseDataset = "datasets\showcase_fintrace_v1",
    [string]$OutputRoot = "runtime\regression_check"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [System.Text.Encoding]::UTF8
[Console]::OutputEncoding = [System.Text.Encoding]::UTF8
$env:PYTHONIOENCODING = "utf-8"

function Show-FinTraceReport {
    param(
        [string]$ReportPath,
        [string]$Name
    )

    if (-not (Test-Path $ReportPath)) {
        Write-Host "missing report: $ReportPath"
        return
    }

    $report = Get-Content $ReportPath -Raw -Encoding UTF8 | ConvertFrom-Json
    $metrics = $report.metrics
    Write-Host ""
    Write-Host "[$Name]"
    Write-Host ("dataset: {0}" -f $report.dataset_version)
    Write-Host ("mode: {0}" -f $report.evaluation_mode)
    Write-Host ("cases: {0}" -f $metrics.total_cases)
    Write-Host ("decision_accuracy: {0:P2}" -f [double]$metrics.decision_accuracy)
    Write-Host ("hard_precision: {0:P2}" -f [double]$metrics.hard_precision)
    Write-Host ("hard_recall: {0:P2}" -f [double]$metrics.hard_recall)
    Write-Host ("flexible_accuracy: {0:P2}" -f [double]$metrics.flexible_accuracy)
    Write-Host ("field_accuracy: {0:P2}" -f [double]$metrics.field_accuracy)
    Write-Host ("case_errors: {0}" -f $metrics.case_errors.Count)

    foreach ($target in $metrics.target_status.PSObject.Properties) {
        Write-Host ("  - {0}: {1}" -f $target.Name, $target.Value)
    }
}

Write-Host "== FinTrace regression check =="
python -m unittest discover -s tests -v

python cli.py eval-frozen $FinTraceDataset --output-root "$OutputRoot\fintrace_redteam"
python cli.py eval-frozen $RedAttackDataset --output-root "$OutputRoot\red_attack_v1"
python cli.py eval-frozen $ShowcaseDataset --output-root "$OutputRoot\showcase_fintrace"

Show-FinTraceReport "$OutputRoot\fintrace_redteam\frozen_evaluation_report_fintrace-redteam-v1.json" "fintrace-redteam-v1"
Show-FinTraceReport "$OutputRoot\red_attack_v1\frozen_evaluation_report_red_attack_v1.json" "red_attack_v1"
Show-FinTraceReport "$OutputRoot\showcase_fintrace\frozen_evaluation_report_showcase_fintrace_v1.json" "showcase_fintrace_v1"

Write-Host ""
Write-Host "== regression check complete =="
