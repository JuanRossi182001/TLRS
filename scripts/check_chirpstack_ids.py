import argparse
import asyncio
import os
import subprocess
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


DEFAULT_ENV_FILES = [
    PROJECT_ROOT / "infra" / "chirpstack-simulator" / ".env",
    PROJECT_ROOT / "infra" / "chirpstack" / ".env",
    PROJECT_ROOT / ".env",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Compare ChirpStack IDs from env against Manea devices table"
    )
    parser.add_argument(
        "--env-file",
        action="append",
        dest="env_files",
        default=[],
        help="Extra env file to load. Can be passed multiple times.",
    )
    parser.add_argument(
        "--no-docker-fallback",
        action="store_true",
        help="Do not retry inside docker compose backend when local dependencies are missing.",
    )
    return parser.parse_args()


def load_env_files(extra_env_files: list[str]) -> list[Path]:
    loaded: list[Path] = []

    for candidate in [Path(item) for item in extra_env_files] + DEFAULT_ENV_FILES:
        resolved = candidate if candidate.is_absolute() else (PROJECT_ROOT / candidate)
        if not resolved.exists():
            continue
        _load_env_file(resolved)
        loaded.append(resolved)

    return loaded


def _load_env_file(path: Path) -> None:
    for raw_line in path.read_text(encoding="utf-8").splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        if not key or key in os.environ:
            continue

        cleaned = value.strip()
        if cleaned.startswith("="):
            cleaned = cleaned[1:].strip()
        os.environ[key] = cleaned.strip("\"'")


async def async_main(extra_env_files: list[str]) -> int:
    from sqlalchemy import select

    from src.db.config.config import sessionlocal
    from src.models.device import Device

    loaded_files = load_env_files(extra_env_files)
    if loaded_files:
        print("Loaded env files:", flush=True)
        for env_file in loaded_files:
            print(f"- {env_file}", flush=True)

    application_id = os.getenv("CHIRPSTACK_APPLICATION_ID")
    dev_eui = (os.getenv("CHIRPSTACK_DEV_EUI") or "").replace(" ", "").lower()
    device_profile_id = os.getenv("CHIRPSTACK_DEVICE_PROFILE_ID")

    if not application_id or not dev_eui:
        print("CHIRPSTACK_APPLICATION_ID and CHIRPSTACK_DEV_EUI are required")
        return 1

    async with sessionlocal() as db:
        stmt = select(Device).where(
            Device.chirpstack_dev_eui == dev_eui,
            Device.deleted == "N",
        )
        result = await db.execute(stmt)
        device = result.scalar_one_or_none()

    if device is None:
        print(f"Device not found in Manea for chirpstack_dev_eui={dev_eui}")
        return 1

    print(f"Device found: id_device={device.id_device} serial={device.serial} name={device.name}")

    mismatches: list[str] = []
    if device.chirpstack_application_id != application_id:
        mismatches.append(
            f"application_id mismatch env={application_id} db={device.chirpstack_application_id}"
        )

    if device.chirpstack_dev_eui != dev_eui:
        mismatches.append(
            f"dev_eui mismatch env={dev_eui} db={device.chirpstack_dev_eui}"
        )

    if device_profile_id and device.chirpstack_device_profile_id != device_profile_id:
        mismatches.append(
            "device_profile_id mismatch "
            f"env={device_profile_id} db={device.chirpstack_device_profile_id}"
        )

    if mismatches:
        print("Mismatches detected:")
        for mismatch in mismatches:
            print(f"- {mismatch}")
        return 1

    print("ChirpStack IDs are aligned between env and Manea")
    return 0


def main() -> int:
    args = parse_args()
    try:
        return asyncio.run(async_main(args.env_files))
    except ModuleNotFoundError as exc:
        if args.no_docker_fallback:
            raise

        print(
            "Local Python is missing project dependencies. "
            "Retrying inside docker compose backend...",
            flush=True,
        )
        command = [
            "docker",
            "compose",
            "exec",
            "-T",
            "backend",
            "python",
            "scripts/check_chirpstack_ids.py",
            "--no-docker-fallback",
        ]
        for env_file in args.env_files:
            command.extend(["--env-file", env_file])

        completed = subprocess.run(command, cwd=PROJECT_ROOT)
        return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())
