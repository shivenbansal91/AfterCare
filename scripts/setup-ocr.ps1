$ErrorActionPreference = 'Stop'
$projectRoot = Split-Path $PSScriptRoot -Parent
$ocrRoot = Join-Path $projectRoot '.tools/ocr'
conda create --prefix $ocrRoot --override-channels --channel conda-forge tesseract=5.5.3 -y
if ($LASTEXITCODE -ne 0) { throw 'Tesseract installation failed.' }
foreach ($language in @('eng', 'osd')) {
    Copy-Item -LiteralPath (Join-Path $ocrRoot "share/tessdata/$language.traineddata") -Destination (Join-Path $ocrRoot "Library/share/tessdata/$language.traineddata")
}
& (Join-Path $ocrRoot 'Library/bin/tesseract.exe') --version
