<#
.SYNOPSIS
    Terraproof Repository Integrity & Frontmatter Validator (PowerShell native).
#>

$repoRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
$errors = [System.Collections.Generic.List[string]]::new()
$warnings = [System.Collections.Generic.List[string]]::new()

Write-Host ("=" * 60) -ForegroundColor Cyan
Write-Host "Terraproof Repository Integrity & Verification Suite (PowerShell)" -ForegroundColor Cyan
Write-Host "Repository Root: $repoRoot" -ForegroundColor Cyan
Write-Host ("=" * 60) -ForegroundColor Cyan

# 1. Validate skills
Write-Host "[1/3] Validating skills and frontmatter..."
$skillsDir = Join-Path $repoRoot "skills"
if (-not (Test-Path $skillsDir)) {
    $errors.Add("skills/ directory not found.")
} else {
    $skillFolders = Get-ChildItem -Path $skillsDir -Directory
    foreach ($folder in $skillFolders) {
        $skillName = $folder.Name
        $skillMd = Join-Path $folder.FullName "SKILL.md"
        $upstreamMd = Join-Path $folder.FullName "UPSTREAM.md"

        if (-not (Test-Path $skillMd)) {
            $errors.Add("Skill '$skillName' is missing SKILL.md")
            continue
        }

        $content = [System.IO.File]::ReadAllText($skillMd, [System.Text.Encoding]::UTF8)
        if (-not $content.StartsWith("---")) {
            $errors.Add("Skill '$skillName': SKILL.md missing valid YAML frontmatter (--- delimiters)")
        } else {
            $parts = $content.Split(@("---"), 3, [System.StringSplitOptions]::None)
            if ($parts.Length -lt 3) {
                $errors.Add("Skill '$skillName': Incomplete YAML frontmatter")
            } else {
                $fmText = $parts[1]
                $hasName = $fmText -match '(?m)^\s*name\s*:\s*.+$'
                $hasDesc = $fmText -match '(?m)^\s*description\s*:\s*.+$'
                if (-not $hasName) {
                    $errors.Add("Skill '$skillName': Frontmatter missing required 'name' property")
                }
                if (-not $hasDesc) {
                    $errors.Add("Skill '$skillName': Frontmatter missing required 'description' property")
                }
            }
        }

        if ($content -match 'Goal\s*\r?\n\s*TODO') {
            $warnings.Add("Skill '$skillName' appears to be an unpopulated placeholder with TODO sections.")
        }

        if (-not (Test-Path $upstreamMd)) {
            $warnings.Add("Skill '$skillName' does not have an UPSTREAM.md provenance record.")
        }
    }
}

# 2. Validate markdown links
Write-Host "[2/3] Validating markdown links and references..."
# Skip VCS data, virtualenvs, dependencies, and build output (same directories as validate_repo.py)
$skippedDirPattern = '\\(\.git|\.venv|venv|node_modules|dist|build|\.pytest_cache)\\'
$mdFiles = Get-ChildItem -Path $repoRoot -Recurse -Filter *.md | Where-Object { $_.FullName.Substring($repoRoot.Length) -notmatch $skippedDirPattern }
$linkPattern = '\[([^\]]+)\]\(([^)]+)\)'

foreach ($file in $mdFiles) {
    $relFile = $file.FullName.Substring($repoRoot.Length + 1)
    $content = [System.IO.File]::ReadAllText($file.FullName, [System.Text.Encoding]::UTF8)

    if ($content -match 'file:///[a-zA-Z]:/') {
        $errors.Add("File '$relFile' contains machine-specific 'file:///' link.")
    }
    if ($content -match '\[.*?\]\([a-zA-Z]:[/\\]') {
        $errors.Add("File '$relFile' contains absolute local drive link.")
    }

    # Strip code blocks to avoid false link matches inside syntax examples
    $textWithoutCode = [regex]::Replace($content, '```[\s\S]*?```', '')

    $matches = [regex]::Matches($textWithoutCode, $linkPattern)
    foreach ($m in $matches) {
        $target = $m.Groups[2].Value.Trim()
        if ($target -match '^(https?://|mailto:|#|ftp://)') {
            continue
        }
        $targetClean = ($target.Split('#')[0]).Split('?')[0].Trim()
        if ([string]::IsNullOrWhiteSpace($targetClean)) {
            continue
        }

        $resolved = [System.IO.Path]::GetFullPath([System.IO.Path]::Combine($file.DirectoryName, ($targetClean -replace '/', '\')))
        if (-not (Test-Path $resolved)) {
            $errors.Add("Broken link in '$relFile': target '$target' does not exist on disk.")
        }
    }
}

# 3. Validate domain routing
Write-Host "[3/3] Validating domain routing references..."
$routingFile = Join-Path $repoRoot "routing\DOMAIN_ROUTING.md"
if (Test-Path $routingFile) {
    $content = [System.IO.File]::ReadAllText($routingFile, [System.Text.Encoding]::UTF8)
    $instMatches = [regex]::Matches($content, 'instructions/[\w-]+\.md')
    foreach ($m in $instMatches) {
        $instPath = Join-Path $repoRoot ($m.Value -replace '/', '\')
        if (-not (Test-Path $instPath)) {
            $errors.Add("DOMAIN_ROUTING.md references missing instruction: '$($m.Value)'")
        }
    }

    $skillMatches = [regex]::Matches($content, 'skills/([\w-]+)')
    foreach ($m in $skillMatches) {
        $skillDir = Join-Path $repoRoot ("skills\" + $m.Groups[1].Value)
        if (-not (Test-Path $skillDir)) {
            $errors.Add("DOMAIN_ROUTING.md references missing skill: 'skills/$($m.Groups[1].Value)'")
        }
    }
}

Write-Host ("-" * 60)
if ($warnings.Count -gt 0) {
    Write-Host "WARNINGS ($($warnings.Count)):" -ForegroundColor Yellow
    foreach ($w in $warnings) {
        Write-Host "  - $w" -ForegroundColor Yellow
    }
    Write-Host ("-" * 60)
}

if ($errors.Count -gt 0) {
    Write-Host "FAILED with $($errors.Count) error(s):" -ForegroundColor Red
    foreach ($e in $errors) {
        Write-Host "  - $e" -ForegroundColor Red
    }
    Write-Host ("=" * 60) -ForegroundColor Red
    exit 1
} else {
    Write-Host "SUCCESS: All skills, frontmatter, and link references passed validation!" -ForegroundColor Green
    Write-Host ("=" * 60) -ForegroundColor Green
    exit 0
}
