"""Allow running the app with python -m skrudj."""

import asyncio

from skrudj.main import run


if __name__ == "__main__":
    asyncio.run(run())
