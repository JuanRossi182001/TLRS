import argparse
import asyncio
import sys
from pathlib import Path

from sqlalchemy import select

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from src.db.config.config import sessionlocal
from src.models.chirpstack_event import ChirpStackEvent


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Mark old ChirpStack join/log unsupported events as processed."
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many rows would be updated without committing changes.",
    )
    return parser.parse_args()


async def async_main(dry_run: bool) -> int:
    async with sessionlocal() as db:
        stmt = (
            select(ChirpStackEvent)
            .where(
                ChirpStackEvent.event_type.in_(("join", "log")),
                ChirpStackEvent.error_message.like(
                    "Unsupported ChirpStack event type:%"
                ),
            )
            .order_by(ChirpStackEvent.id.asc())
        )
        result = await db.execute(stmt)
        events = result.scalars().all()

        print(f"Matched events: {len(events)}")
        if not events:
            return 0

        if dry_run:
            return 0

        for event in events:
            event.processed = True
            event.error_message = None
            db.add(event)

        await db.commit()
        print(f"Updated events: {len(events)}")
        return 0


def main() -> int:
    args = parse_args()
    return asyncio.run(async_main(dry_run=args.dry_run))


if __name__ == "__main__":
    raise SystemExit(main())
