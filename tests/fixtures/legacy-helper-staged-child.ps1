param([string]$Action)
if ($Action -cne 'health') { throw 'Unexpected fixture acquisition' }
[Console]::Out.WriteLine('{"status":"ok","fixture":"one-shot-read"}')
