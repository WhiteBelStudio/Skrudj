"""Allow running the app with python -m skrudj."""

import asyncio

from .main import run


if __name__ == "__main__":
    asyncio.run(run())
