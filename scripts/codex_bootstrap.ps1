$ErrorActionPreference = 'Stop'

Write-Host 'JSAN PLA - Codex bootstrap' -ForegroundColor Cyan

if (-not (Get-Command git -ErrorAction SilentlyContinue)) {
    throw 'Git is required.'
}
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    throw 'Node.js is required.'
}
if (-not (Get-Command npm -ErrorAction SilentlyContinue)) {
    throw 'npm is required.'
}

if (-not (Get-Command codex -ErrorAction SilentlyContinue)) {
    Write-Host 'Installing OpenAI Codex CLI...'
    npm i -g @openai/codex
}

Write-Host ('Codex: ' + (codex --version)) -ForegroundColor Green
Write-Host 'Run codex from the repository root, then ask it to read AGENTS.md and CODEX_START_HERE.md.'
