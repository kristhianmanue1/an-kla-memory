import os,sys,json,time,signal
from pathlib import Path
os.environ['AN_KLA_NO_UPDATE_CHECK']='1'
assert not os.environ.get('AN_KLA_STORE_ROOT')
source, destination = map(Path,sys.argv[1:3])
sys.path.insert(0,str(source))
from an_kla.store import MemoryStore
def expire(*_): raise TimeoutError('read-only verification budget')
signal.signal(signal.SIGALRM,expire)
signal.alarm(20)
result={'source':str(source),'store':str(destination/'store')}
try:
    store=MemoryStore(destination/'store')
    head=store.read_current()
    result['head']=head
    t=time.perf_counter()
    result['verify']=store.verify()
    result['verify_s']=time.perf_counter()-t
except Exception as exc:
    result['error']=type(exc).__name__+': '+str(exc)
finally:
    signal.alarm(0)
    (destination/'verify.json').write_text(json.dumps(result,indent=2))
print(json.dumps(result))
