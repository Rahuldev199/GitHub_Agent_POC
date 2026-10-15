"""GitHub Team Stats Agent."""

import os

__version__ = "0.8.1"
__commit__ = os.getenv("GITHUB_MEMBER_ACTIVITY_BUILD_COMMIT", "development")


def full_version() -> str:
    return f"{__version__}+{__commit__}"
