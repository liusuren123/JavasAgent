# Fix Chinese quotes in create_ppt.py
$in = 'scripts/create_ppt.py'
$content = [System.IO.File]::ReadAllText($in, [System.Text.Encoding]::UTF8)
$content = $content.Replace([char]0x201c, "'").Replace([char]0x201d, "'")
[System.IO.File]::WriteAllText($in, $content, [System.Text.Encoding]::UTF8)
Write-Output "Fixed"
