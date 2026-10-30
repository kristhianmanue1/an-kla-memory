"""Cooperative timeout fixture: register identity before deliberately escaping."""
import json
import os
import sys
import time
from pathlib import Path

directory, token = Path(sys.argv[1]), sys.argv[2]
record = directory / (token + ".json")
temporary = record.with_suffix(".tmp")
temporary.write_text(json.dumps({"pid": os.getpid(), "token": token}))
temporary.replace(record)
os.setsid()
time.sleep(300)
