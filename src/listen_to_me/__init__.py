"""Listen To Me — push-to-talk voice typing with a local Whisper model."""

from __future__ import annotations

__version__ = "0.0.0.dev0"

APP_NAME = "Listen To Me"
APP_ID = "listen-to-me"
REPO_URL = "https://github.com/fo0/listen-to-me"
# The download page users are sent to whenever the in-app updater can't serve
# them: a build that can't replace its own binary, an intercepting proxy, or
# just a look at what an older release contained. Derived from REPO_URL so the
# two can never drift apart.
RELEASES_URL = f"{REPO_URL}/releases"
