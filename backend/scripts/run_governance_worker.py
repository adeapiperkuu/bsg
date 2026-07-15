"""Run the durable Governance job worker without Docker or a web process."""

from __future__ import annotations

import argparse
import asyncio
import logging
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.agents.governance.services.job_service import process_governance_job_queue  # noqa: E402
from app.core.config import get_settings  # noqa: E402
from app.db.session import dispose_engine  # noqa: E402


async def main(*, once: bool) -> None:
    settings = get_settings()
    try:
        while True:
            processed = await process_governance_job_queue()
            if once:
                return
            if processed == 0:
                await asyncio.sleep(settings.governance_job_poll_interval_seconds)
    finally:
        await dispose_engine()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--once", action="store_true", help="Process one queue batch and exit.")
    args = parser.parse_args()
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main(once=args.once))
