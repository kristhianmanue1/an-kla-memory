import subprocess,sys
from pathlib import Path
root=Path('/private/tmp/adr0061-comparison')
for name in ('baseline-1','phase-a-1','phase-b-1','baseline-2','phase-b-2','baseline-3','phase-b-3'):
    source='phase-a' if name.startswith('phase-a') else 'phase-b' if name.startswith('phase-b') else 'baseline'
    subprocess.run([sys.executable,'/private/tmp/adr0061-verify-worker.py','/private/tmp/adr0061-'+source+'-source',str(root/name)],check=True,timeout=25)
