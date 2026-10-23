import argparse
import os
import secrets
from pathlib import Path

import uvicorn
from cryptography.fernet import Fernet

from axonhub.config import Settings


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Python AI gateway")
    parser.add_argument("command", nargs="?", choices=["serve", "init"], default="serve")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8091)
    parser.add_argument("--env-file", default=".env", help="Local credential configuration")
    args = parser.parse_args()
    if args.command == "init":
        try:
            descriptor = os.open(args.env_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        except FileExistsError:
            parser.exit(
                1, "Configuration already exists; existing credentials were left unchanged\n"
            )
        with os.fdopen(descriptor, "w") as handle:
            handle.write(f"AXON_ADMIN_TOKEN={secrets.token_urlsafe(32)}\n")
            handle.write(f"AXON_ENCRYPTION_KEY={Fernet.generate_key().decode()}\n")
        print(f"Created {Path(args.env_file).resolve()}. Keep this file private and backed up.")
        return
    settings = Settings(_env_file=args.env_file)
    if len(settings.admin_token.get_secret_value()) < 32:
        parser.exit(1, "Run axonhub init or configure a strong AXON_ADMIN_TOKEN first\n")
    try:
        Fernet(settings.encryption_key.get_secret_value().encode())
    except (ValueError, TypeError):
        parser.exit(1, "Configure AXON_ENCRYPTION_KEY using axonhub init\n")
    from axonhub.app import create_app

    uvicorn.run(create_app(settings), host=args.host, port=args.port)
