"""Exercise the packaged helper and DPAPI without network or real credentials."""

import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile

from msal import SerializableTokenCache
from msal_extensions import FilePersistenceWithDataProtection


def main():
    root = Path(__file__).resolve().parent.parent
    executable = root / "KnightAgentCopilot.exe"
    settings = {"client_id": "d47047a2-d39c-4171-bb1b-3c9d68f37d0b", "tenant": "organizations"}
    identity = hashlib.sha256((settings["client_id"] + ":" + settings["tenant"]).encode()).hexdigest()
    with tempfile.TemporaryDirectory(prefix="copilot-package-", dir=root / "build") as temporary:
        env = dict(os.environ, LOCALAPPDATA=temporary)
        path = Path(temporary) / "KnightAgent" / "Copilot" / (identity + ".bin")
        cache = SerializableTokenCache()
        # Synthetic account only. No access/refresh tokens or real identity.
        cache.deserialize(json.dumps({"Account": {"synthetic-account": {
            "home_account_id": "synthetic", "environment": "login.microsoftonline.com",
            "realm": "organizations", "username": "package-test@example.invalid",
            "local_account_id": "synthetic", "authority_type": "MSSTS",
        }}}))
        FilePersistenceWithDataProtection(str(path)).save(cache.serialize())

        def call(operation, values=settings):
            result = subprocess.run(
                [str(executable)], input=json.dumps({"version": 1, "operation": operation, "settings": values}).encode(),
                stdout=subprocess.PIPE, stderr=subprocess.PIPE, timeout=40, cwd=root, env=env,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            assert result.returncode == 0, "Packaged helper did not exit successfully"
            payload = json.loads(result.stdout)
            assert payload.get("version") == 1 and "error" not in payload, "Invalid helper response"
            assert "access_token" not in result.stdout.decode(), "Unexpected credential field"
            return payload["result"]

        assert call("status", {"client_id": "", "tenant": "organizations"})["status"] == "setup_required"
        signed_in = call("status")
        assert signed_in["status"] == "authenticated"
        assert signed_in["account"] == "package-test@example.invalid"
        assert call("logout")["status"] == "disconnected"
        assert call("status")["status"] == "disconnected"
    print("Packaged Copilot helper: setup, synthetic DPAPI account and local logout passed; no login or network used.")


if __name__ == "__main__":
    main()
