"""Application startup banner with professional styling and attribution."""

from __future__ import annotations

import sys

BANNER_TEXT = """
\033[1;36m========================================================================================\033[0m
\033[1;32m  telegram-chat-automation v1.0\033[0m
\033[1;30m  ~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m

  \033[1;37mA production-ready automation tool for automating whole telegram messages from\033[0m
  \033[1;37mbot-bot, account-bot, groups messages etc all from your main account.\033[0m

  \033[1;34mRepository:\033[0m \033[0;37m(Configured in project root)\033[0m
  \033[1;34mAuthor:    \033[0m \033[1;33mMohammad Kaif Raja (mkr-infinity)\033[0m
  \033[1;34mCopyright: \033[0m \033[0;37mCopyright (c) Mohammad Kaif Raja. All Rights Reserved.\033[0m
\033[1;30m~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m
\033[1;31m~  If you modify, redistribute, or sell anything made from my things without my         ~\033[0m
\033[1;31m~  permission, it is strictly prohibited.                                              ~\033[0m
\033[1;30m~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~~\033[0m
  \033[1;33mUnauthorized removal of attribution is strictly prohibited.\033[0m
\033[1;36m========================================================================================\033[0m
"""


def print_banner() -> None:
    """Print the professional startup banner to stdout."""
    # Check if stdout supports ANSI colors, otherwise strip or print clean
    if hasattr(sys.stdout, "isatty") and sys.stdout.isatty():
        sys.stdout.write(BANNER_TEXT + "\n")
    else:
        # Non-TTY clean fallback
        import re
        clean = re.sub(r"\033\[[0-9;]*m", "", BANNER_TEXT)
        sys.stdout.write(clean + "\n")
    sys.stdout.flush()
