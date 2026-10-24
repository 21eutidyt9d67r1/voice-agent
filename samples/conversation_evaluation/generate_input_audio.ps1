param(
    [Parameter(Mandatory = $true)]
    [string]$OutputDirectory,
    [string]$PythonExecutable = "python",
    [string]$Voice = "Microsoft Zira Desktop"
)

$ErrorActionPreference = "Stop"
Add-Type -AssemblyName System.Speech
$promptsJson = & $PythonExecutable -c 'import json,sys; sys.path.insert(0,sys.argv[1]); import evaluate_conversation as s; print(json.dumps({"travel":s.QUESTIONS,"return":s.SUPPORT_QUESTIONS}))' $PSScriptRoot
if ($LASTEXITCODE -ne 0) {
    throw "Could not load sample prompts with the selected Python environment."
}
$prompts = $promptsJson | ConvertFrom-Json
[System.IO.Directory]::CreateDirectory($OutputDirectory) | Out-Null
$directory = (Resolve-Path -LiteralPath $OutputDirectory).Path
$synthesizer = [System.Speech.Synthesis.SpeechSynthesizer]::new()
try {
    $synthesizer.SelectVoice($Voice)
    $format = [System.Speech.AudioFormat.SpeechAudioFormatInfo]::new(
        24000,
        [System.Speech.AudioFormat.AudioBitsPerSample]::Sixteen,
        [System.Speech.AudioFormat.AudioChannel]::Mono
    )
    foreach ($category in $prompts.PSObject.Properties) {
        $index = 0
        foreach ($text in $category.Value) {
            $index++
            $path = Join-Path $directory "$($category.Name)-$index.wav"
            $synthesizer.SetOutputToWaveFile($path, $format)
            $synthesizer.Speak([string]$text)
            $synthesizer.SetOutputToNull()
            Write-Output "Generated synthetic spoken input: $path"
        }
    }
}
finally {
    $synthesizer.Dispose()
}
