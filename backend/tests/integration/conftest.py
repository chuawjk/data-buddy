"""Integration-test configuration.

Integration tests use real file I/O and real HTTP cycles but skip the
OpenCode binary so they run without the external process installed.
"""

import os

os.environ["SKIP_OPENCODE"] = "1"
