import argparse

from src.integrations.chirpstack.api_client import (
    ChirpStackAlreadyExistsError,
    ChirpStackApiClient,
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Create or update a ChirpStack device and OTAA keys for smoke testing.",
    )
    parser.add_argument("--dev-eui", required=True)
    parser.add_argument("--join-eui", required=True)
    parser.add_argument("--app-key", required=True)
    parser.add_argument("--application-id", required=True)
    parser.add_argument("--device-profile-id", required=True)
    parser.add_argument("--name", default="Manea Test Device")
    parser.add_argument("--description", default="Created by Manea smoke test")
    parser.add_argument("--serial", default="MANEA-TEST-DEVICE")
    parser.add_argument("--disabled", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    client = ChirpStackApiClient()

    try:
        client.create_device(
            dev_eui=args.dev_eui,
            name=args.name,
            application_id=args.application_id,
            device_profile_id=args.device_profile_id,
            join_eui=args.join_eui,
            description=args.description,
            is_disabled=args.disabled,
            tags={"serial": args.serial},
        )
        created = True
    except ChirpStackAlreadyExistsError:
        created = False
        client.update_device(
            dev_eui=args.dev_eui,
            name=args.name,
            application_id=args.application_id,
            device_profile_id=args.device_profile_id,
            join_eui=args.join_eui,
            description=args.description,
            is_disabled=args.disabled,
            tags={"serial": args.serial},
        )

    try:
        client.create_device_keys(dev_eui=args.dev_eui, app_key=args.app_key)
        keys_created = True
    except ChirpStackAlreadyExistsError:
        keys_created = False
        client.update_device_keys(dev_eui=args.dev_eui, app_key=args.app_key)

    print("ChirpStack device provisioning smoke test completed")
    print(f"dev_eui={args.dev_eui.lower()}")
    print(f"join_eui={args.join_eui.lower()}")
    print(f"application_id={args.application_id}")
    print(f"device_profile_id={args.device_profile_id}")
    print(f"device_created={created}")
    print(f"keys_created={keys_created}")
    print(f"app_key_last4={args.app_key.lower()[-4:]}")


if __name__ == "__main__":
    main()
