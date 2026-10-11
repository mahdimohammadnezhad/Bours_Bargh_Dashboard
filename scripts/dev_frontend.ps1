# Run the Next.js dev server locally (requires the backend running - see dev_backend.ps1).
Set-Location "$PSScriptRoot\..\frontend"
if (-not (Test-Path "node_modules")) {
    npm install
}
npm run dev
