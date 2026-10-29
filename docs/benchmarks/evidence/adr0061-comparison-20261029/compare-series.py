import subprocess,sys,json
from pathlib import Path
out=Path('/private/tmp/adr0061-comparison')
sequence=[('phase-b-1','phase-b'),('baseline-2','baseline'),('phase-b-2','phase-b'),('baseline-3','baseline'),('phase-b-3','phase-b')]
for label,source in sequence:
    subprocess.run([sys.executable,'/private/tmp/adr0061-compare-worker.py',
                    '/private/tmp/adr0061-'+source+'-source',str(out/label)],check=True,timeout=110)
