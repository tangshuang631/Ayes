$ErrorActionPreference = 'Stop'
$SkillDir = Split-Path -Parent (Split-Path -Parent $MyInvocation.MyCommand.Path)
$SrcDir = Join-Path $SkillDir 'src'
$env:PYTHONPATH = $SrcDir
$env:AYES_RUNTIME_DIR = Join-Path $SkillDir 'runtime'
python -m ayes.cli.windows_tray @args
exit $LASTEXITCODE
