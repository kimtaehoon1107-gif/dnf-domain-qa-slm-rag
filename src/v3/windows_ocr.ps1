param(
    [string]$LanguageTag = "ko"
)

$ErrorActionPreference = "Stop"
$OutputEncoding = [Console]::OutputEncoding = [System.Text.UTF8Encoding]::new($false)

Add-Type -AssemblyName System.Runtime.WindowsRuntime
$null = [Windows.Media.Ocr.OcrEngine, Windows.Media.Ocr, ContentType=WindowsRuntime]
$null = [Windows.Globalization.Language, Windows.Globalization, ContentType=WindowsRuntime]
$null = [Windows.Storage.StorageFile, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.FileAccessMode, Windows.Storage, ContentType=WindowsRuntime]
$null = [Windows.Storage.Streams.IRandomAccessStream, Windows.Storage.Streams, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.BitmapDecoder, Windows.Graphics.Imaging, ContentType=WindowsRuntime]
$null = [Windows.Graphics.Imaging.SoftwareBitmap, Windows.Graphics.Imaging, ContentType=WindowsRuntime]

$asTaskMethod = [System.WindowsRuntimeSystemExtensions].GetMethods() |
    Where-Object {
        $_.Name -eq "AsTask" -and
        $_.IsGenericMethodDefinition -and
        $_.GetParameters().Count -eq 1
    } |
    Select-Object -First 1

function Await-WinRtOperation {
    param(
        [Parameter(Mandatory = $true)]$Operation,
        [Parameter(Mandatory = $true)][Type]$ResultType
    )
    $method = $script:asTaskMethod.MakeGenericMethod($ResultType)
    $task = $method.Invoke($null, @($Operation))
    $task.Wait()
    return $task.Result
}

$language = [Windows.Globalization.Language]::new($LanguageTag)
$engine = [Windows.Media.Ocr.OcrEngine]::TryCreateFromLanguage($language)
if ($null -eq $engine) {
    throw "Windows OCR language is unavailable: $LanguageTag"
}

while (($line = [Console]::In.ReadLine()) -ne $null) {
    if ([string]::IsNullOrWhiteSpace($line)) {
        continue
    }
    $request = $line | ConvertFrom-Json
    $response = [ordered]@{
        id = $request.id
        path = $request.path
        status = "failed"
        text = ""
        error = $null
    }
    $stream = $null
    $bitmap = $null
    try {
        $absolutePath = [System.IO.Path]::GetFullPath([string]$request.path)
        $file = Await-WinRtOperation (
            [Windows.Storage.StorageFile]::GetFileFromPathAsync($absolutePath)
        ) ([Windows.Storage.StorageFile])
        $stream = Await-WinRtOperation (
            $file.OpenAsync([Windows.Storage.FileAccessMode]::Read)
        ) ([Windows.Storage.Streams.IRandomAccessStream])
        $decoder = Await-WinRtOperation (
            [Windows.Graphics.Imaging.BitmapDecoder]::CreateAsync($stream)
        ) ([Windows.Graphics.Imaging.BitmapDecoder])
        $bitmap = Await-WinRtOperation (
            $decoder.GetSoftwareBitmapAsync()
        ) ([Windows.Graphics.Imaging.SoftwareBitmap])
        $result = Await-WinRtOperation (
            $engine.RecognizeAsync($bitmap)
        ) ([Windows.Media.Ocr.OcrResult])
        $response.status = "success"
        $response.text = [string]$result.Text
    }
    catch {
        $response.error = $_.Exception.ToString()
    }
    finally {
        if ($null -ne $bitmap) {
            $bitmap.Dispose()
        }
        if ($null -ne $stream) {
            $stream.Dispose()
        }
    }
    $response | ConvertTo-Json -Compress
}
