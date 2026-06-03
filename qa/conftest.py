"""QA suite conftest.

Sets up sys.path so that 'backend' is importable when running
``pytest qa/`` from the repo root (outside the backend/ uv project).

Note: async tests in this suite use @pytest.mark.asyncio.  When running
under the backend uv project (asyncio_mode=STRICT) the mark is required
for each async test — which the tests do carry.  When running under
asyncio_mode=AUTO the mark is redundant but harmless.
"""

from __future__ import annotations

import sys
from pathlib import Path


# Add backend/ to sys.path so `import backend` works.
_BACKEND_DIR = Path(__file__).parent.parent / "backend"
if str(_BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(_BACKEND_DIR))
