import os
import sys
import importlib
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import db_supabase
sys.modules['db'] = db_supabase

mods = ['handlers', 'server', 'db_supabase', 'notes', 'ai']
for m in mods:
    try:
        importlib.import_module(m)
        print(m + ': OK')
    except Exception as e:
        print(m + ': ERROR ->', e)
