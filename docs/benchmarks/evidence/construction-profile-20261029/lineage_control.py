import sys,json
sys.path.insert(0,'/Users/krisnova/www/an-kla-memory')
from an_kla.identity_evidence import _is_ancestor, validate_bound_descendants
class SyntheticChain:
    def _read_json_object(self,kind,identifier):
        n=int(identifier)
        return {'parent':str(n-1) if n else None,'store_identity':'identity'}
s=SyntheticChain()
rows=[]
for n in (9999,10000,20000):
    try:
        validate_bound_descendants(s,str(n),'0','identity')
        bound='accepted'
    except Exception as exc:
        bound=str(exc)
    rows.append({'edges':n,'ancestor':_is_ancestor(s,'0',str(n)),'bound_descendants':bound})
print(json.dumps({'method':'synthetic in-memory ancestry, no disk store; positive 9999 vs negative 10000/20000', 'results':rows},indent=2))
