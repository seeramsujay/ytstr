import sys
from pathlib import Path

# Ensure src/ has precedence over repo root to avoid shadowing by ytstr.py
src_path = str(Path(__file__).resolve().parent.parent / 'src')
if src_path not in sys.path:
    sys.path.insert(0, src_path)
elif sys.path[0] != src_path:
    sys.path.remove(src_path)
    sys.path.insert(0, src_path)
