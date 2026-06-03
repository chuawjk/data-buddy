"""Unit-test configuration.

Unit tests never start real external processes.  Force SKIP_OPENCODE=1 so the
lifespan skips OpenCode binary launch/shutdown, which otherwise blocks the
test session while waiting for a process that is not needed for unit testing.
"""

import os

os.environ["SKIP_OPENCODE"] = "1"
