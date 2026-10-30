"""Synthetic-store evidence only; no canonical memory or product edits."""
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch
sys.path.insert(0, '/Users/krisnova/www/an-kla-memory')
from an_kla import hook_runs
from an_kla.attest import ensure_attest_files
from an_kla.store import MemoryStore

def scenario(timestamps):
    with tempfile.TemporaryDirectory(prefix='ankla-ci-hook-idempotency-') as temporary:
        root = Path(temporary)
        store = MemoryStore(root)
        store.initialize()
        ensure_attest_files(root)
        outputs = []
        with patch.object(hook_runs, '_utc_now', side_effect=timestamps):
            for _ in timestamps:
                outputs.append(hook_runs.mint_hook_run(store, hook_id='before-task-retrieve',
                    trigger='before_task', action='retrieve', exit_code=0,
                    subject={'kind':'query','query':'x','budget':100}, run_id='same-run'))
        files = list((root/'.an-kla/hook-runs/runs/sha256').glob('*.json'))
        entries = [json.loads(path.read_text()) for path in files]
        return {'object_count':len(files), 'run_ids':[e['run_id'] for e in entries],
                'observed_at':[e['observed_at'] for e in entries],
                'digests':[out['digest'] for out in outputs]}

same = '2026-10-29T00:00:00Z'
result = {'same_clock_positive_control':scenario([same,same]),
          'clock_advanced_identical_public_arguments':scenario([same,'2026-10-29T00:00:01Z'])}
assert result['same_clock_positive_control']['object_count']==1
assert result['clock_advanced_identical_public_arguments']['object_count']==2
Path(sys.argv[1]).write_text(json.dumps(result,indent=2)+'\n')
print(json.dumps(result,indent=2))
