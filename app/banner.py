"""Application startup banner with professional styling and attribution."""

from __future__ import annotations

import sys

BANNER_TEXT = """
\033[1;36m========================================================================================\033[0m
\033[1;32m  TeleAutomator - Telegram Chat Automation v1.0\033[0m
\033[1;30m  ~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m

  \033[1;37mA production-ready automation tool for automating whole telegram messages from\033[0m
  \033[1;37mbot-bot, account-bot, groups messages etc all from your main account.\033[0m

  \033[1;34mAuthor:    \033[0m \033[1;33mMohammad Kaif Raja (mkr-infinity)\033[0m
  \033[1;34mTelegram:  \033[0m \033[1;36m@mkr_infinity\033[0m \033[0;37m(https://t.me/mkr_infinity)\033[0m
  \033[1;34mInstagram: \033[0m \033[1;35m@mkr_infinity\033[0m \033[0;37m(https://instagram.com/mkr_infinity)\033[0m
  \033[1;34mCopyright: \033[0m \033[0;37mCopyright (c) Mohammad Kaif Raja. All Rights Reserved.\033[0m
\033[1;30m~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m
\033[1;31m~  Unauthorized modification, redistribution, or commercial sale of this software       ~\033[0m
\033[1;31m~  is strictly prohibited without prior written permission. Personal use permitted.     ~\033[0m
\033[1;30m~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m
  \033[1;33mUnauthorized removal of attribution is strictly prohibited.\033[0m
\033[1;36m========================================================================================\033[0m
"""


def print_banner() -> None:
    """Print the professional startup banner to stdout."""
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        sys.stdout.write(BANNER_TEXT + "\n")
    else:
        import re
        clean = re.sub(r"\033\[[0-9;]*m", "", BANNER_TEXT)
        sys.stdout.write(clean + "\n")
    sys.stdout.flush()
