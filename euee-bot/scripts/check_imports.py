import os
import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

os.environ.setdefault('DEV_MODE', '1')

if os.getenv('DEV_MODE', '').lower() in ('1', 'true', 'yes'):
    import db_stub
    sys.modules['db'] = db_stub

mods = ['handlers', 'server', 'db', 'notes', 'ai']
for m in mods:
    try:
        importlib.import_module(m)
        print(m + ': OK')
    except Exception as e:
        print(m + ': ERROR ->', e)
