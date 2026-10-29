param(
    [string]$Python = 'python',
    [ValidateRange(1, 10000)][int]$Limit = 100,
    [ValidateRange(1, 16)][int]$BatchSize = 8,
    [ValidatePattern('^[A-Za-z0-9/_-]+$')][string]$Model = 'turbo'
)
$ErrorActionPreference = 'Stop'
$corpusRoot = (Resolve-Path -LiteralPath (Split-Path -Parent $PSScriptRoot)).Path
$manifest = Join-Path $corpusRoot 'reports\audio-worker.json'
if (Test-Path -LiteralPath $manifest) {
    $state = Get-Content -LiteralPath $manifest -Raw | ConvertFrom-Json
    if ($state.status -eq 'running') {
        $existing = Get-Process -Id $state.pid -ErrorAction SilentlyContinue
        if ($existing) {
            throw "Audio worker PID $($state.pid) is already running."
        }
    }
}
$pythonCommand = (Get-Command $Python -CommandType Application -ErrorAction Stop).Source
$logDirectory = Join-Path $corpusRoot '.cache\workers'
New-Item -ItemType Directory -Path $logDirectory -Force | Out-Null
$runStamp = [DateTime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$stdoutPath = Join-Path $logDirectory "audio-$runStamp.log"
$stderrPath = Join-Path $logDirectory "audio-$runStamp.err.log"
$previousPythonPath = $env:PYTHONPATH
$previousBatchSize = $env:LEVINVERSE_WHISPER_BATCH_SIZE
$previousEncoding = $env:PYTHONIOENCODING
try {
    $env:PYTHONPATH = (Join-Path $corpusRoot 'pipelines') + ';' + (Join-Path $corpusRoot '.venv\Lib\site-packages') + ';' + $previousPythonPath
    $env:LEVINVERSE_WHISPER_BATCH_SIZE = [string]$BatchSize
    $env:PYTHONIOENCODING = 'utf-8'
    $workerArguments = @('-u', '-m', 'levinverse.audio', '--root', ('"' + $corpusRoot + '"'), '--run', '--limit', [string]$Limit, '--model', $Model)
    $workerProcess = Start-Process -FilePath $pythonCommand -ArgumentList $workerArguments -WorkingDirectory $corpusRoot -WindowStyle Hidden -RedirectStandardOutput $stdoutPath -RedirectStandardError $stderrPath -PassThru
} finally {
    $env:PYTHONPATH = $previousPythonPath
    $env:LEVINVERSE_WHISPER_BATCH_SIZE = $previousBatchSize
    $env:PYTHONIOENCODING = $previousEncoding
}
Start-Sleep -Milliseconds 750
$workerProcess.Refresh()
if ($workerProcess.HasExited) {
    throw "Worker exited with code $($workerProcess.ExitCode); inspect $stderrPath and $stdoutPath."
}
[PSCustomObject]@{pid=$workerProcess.Id; status='running'; batch_size=$BatchSize; limit=$Limit; stdout=$stdoutPath; stderr=$stderrPath} | ConvertTo-Json
