import stat
import sys

import pytest
from cryptography.fernet import Fernet

from axonhub.cli import main
from axonhub.config import Settings


def test_init_creates_private_configuration_without_printing_credentials(
    tmp_path, monkeypatch, capsys
):
    path = tmp_path / ".env.python"
    monkeypatch.setattr(sys, "argv", ["axonhub", "init", "--env-file", str(path)])
    main()
    settings = Settings(_env_file=path)
    admin = settings.admin_token.get_secret_value()
    encryption = settings.encryption_key.get_secret_value()
    assert len(admin) >= 32
    Fernet(encryption.encode())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    output = capsys.readouterr().out
    assert admin not in output and encryption not in output


def test_init_preserves_existing_configuration(tmp_path, monkeypatch):
    path = tmp_path / ".env"
    path.write_text("existing configuration\n")
    monkeypatch.setattr(sys, "argv", ["axonhub", "init", "--env-file", str(path)])
    with pytest.raises(SystemExit) as error:
        main()
    assert error.value.code == 1
    assert path.read_text() == "existing configuration\n"
