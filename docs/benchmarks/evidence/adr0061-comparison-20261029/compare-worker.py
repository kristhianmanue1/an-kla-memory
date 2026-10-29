"""Run against one explicit source tree; synthetic store outside that tree."""
import os
os.environ['AN_KLA_NO_UPDATE_CHECK'] = '1'
import sys, json, signal, time, statistics, platform
from pathlib import Path
assert not os.environ.get("AN_KLA_STORE_ROOT"), "synthetic stores require no external store override"
source, destination = map(Path, sys.argv[1:3])
sys.path.insert(0, str(source))
import an_kla
assert Path(an_kla.__file__).resolve().is_relative_to(source.resolve())
from benchmarks.scale.core import make_store, subject_refs, internal_commit, TEXT
class Deadline(BaseException): pass
def expire(*_): raise Deadline()
signal.signal(signal.SIGALRM, expire)
destination.mkdir()
store, current = make_store(destination/'store')
refs = subject_refs(store, 1)
rows, block = [], []
ack = 0
reason = 'target_reached'
start = time.perf_counter()
signal.setitimer(signal.ITIMER_REAL, 90)
try:
    for i in range(500):
        t = time.perf_counter()
        current = internal_commit(store, current, [{'id': f'k-{i}', 'subject_ref': refs[0], 'payload': {'text': TEXT.format(i=i)}}])
        block.append(time.perf_counter()-t)
        ack += 1
        if ack % 100 == 0:
            samples = []
            for _ in range(5):
                t = time.perf_counter()
                store.snapshot()
                samples.append(time.perf_counter()-t)
            row = {'n': ack, 'elapsed_s': time.perf_counter()-start,
                   'block_commit_mean_s': statistics.mean(block),
                   'block_commit_median_s': statistics.median(block),
                   'snapshot_samples_s': samples}
            rows.append(row)
            (destination/'points.json').write_text(json.dumps(rows,indent=2))
            block = []
except Deadline:
    reason = 'hard_wall_deadline'
finally:
    signal.setitimer(signal.ITIMER_REAL, 0)
    (destination/'result.json').write_text(json.dumps({'source':str(source), 'package_path':an_kla.__file__, 'python':sys.version, 'platform':platform.platform(), 'acknowledged_commits':ack, 'reason':reason, 'wall_s':time.perf_counter()-start, 'rows':rows},indent=2))
print(json.dumps({'destination':str(destination),'ack':ack,'reason':reason}))
