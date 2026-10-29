import os
os.environ['AN_KLA_NO_UPDATE_CHECK'] = '1'
import sys, json, time, signal, cProfile, pstats, platform, statistics
from pathlib import Path
sys.path.insert(0, '/Users/krisnova/www/an-kla-memory')
from benchmarks.scale.core import make_store, subject_refs, internal_commit, TEXT

OUT = Path('/private/tmp/ankla-profile-20261029')
class Deadline(BaseException): pass
def alarm(*_): raise Deadline()
signal.signal(signal.SIGALRM, alarm)

def run(name, profiled, budget=90):
    ws = OUT / name
    ws.mkdir()
    store, cur = make_store(ws)
    refs = subject_refs(store, 1)
    profile = cProfile.Profile()
    rows = []
    count = 0
    block = []
    start = time.perf_counter()
    signal.setitimer(signal.ITIMER_REAL, budget)
    reason = 'target_reached'
    try:
        for i in range(20000):
            t = time.perf_counter()
            if profiled: profile.enable()
            try:
                cur = internal_commit(store, cur, [{'id': f'k-{i}', 'subject_ref': refs[0], 'payload': {'text': TEXT.format(i=i)}}])
            finally:
                profile.disable()
            block.append(time.perf_counter() - t)
            count += 1
            if count % 100 == 0:
                samples = []
                for _ in range(5):
                    t = time.perf_counter()
                    snap = store.snapshot()
                    samples.append(time.perf_counter() - t)
                row = {'completed_commits': count, 'revision_number': snap.manifest['revision'], 'elapsed_s': time.perf_counter()-start,
                       'block_commit_mean_s': statistics.mean(block), 'block_commit_median_s': statistics.median(block),
                       'snapshot_samples_s': samples, 'snapshot_median_s': statistics.median(samples)}
                rows.append(row)
                with (OUT / (name + '.jsonl')).open('a') as f: f.write(json.dumps(row)+'\n')
                print(name, json.dumps(row), flush=True)
                block = []
    except Deadline:
        reason = 'hard_wall_deadline'
    finally:
        signal.setitimer(signal.ITIMER_REAL, 0)
        profile.disable()
        result = {'name': name, 'profiled_commits': profiled, 'budget_s': budget, 'target_revisions': 20000,
                  'completed_commits_acknowledged': count, 'stop_reason': reason, 'wall_s': time.perf_counter()-start,
                  'rows': rows, 'python': sys.version, 'platform': platform.platform(),
                  'interrupted_commit_may_have_effects': reason == 'hard_wall_deadline'}
        if profiled:
            profile.dump_stats(str(OUT / 'construction.prof'))
            with (OUT / 'profile.txt').open('w') as f:
                pstats.Stats(profile, stream=f).strip_dirs().sort_stats('cumulative').print_stats(50)
                pstats.Stats(profile, stream=f).strip_dirs().sort_stats('tottime').print_stats(30)
        (OUT / (name + '.json')).write_text(json.dumps(result, indent=2))
        print('RESULT', json.dumps({k:v for k,v in result.items() if k != 'rows'}), flush=True)
run('plain', False)
run('profiled', True)
