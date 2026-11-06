"""Provision the local ISO screenshot worker without printing its password."""
import os
from pathlib import Path
import secrets
import subprocess

ROOT = Path(__file__).resolve().parents[1]
ENV_FILE = ROOT / ".env"


def main():
    lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    entries = dict(line.split("=", 1) for line in lines if "=" in line and not line.lstrip().startswith("#"))
    login = entries.get("ISO_CAPTURE_LOGIN", "").strip()
    password = entries.get("ISO_CAPTURE_PASSWORD", "").strip()
    if bool(login) != bool(password):
        raise SystemExit("Set both capture credentials or leave both blank.")
    if login:
        print("Capture credentials are already configured; existing credentials were left unchanged.")
        return
    login = "iso.capture." + secrets.token_hex(6)
    password = secrets.token_urlsafe(32)
    env = os.environ.copy()
    env["ISO_CAPTURE_PROVISION_LOGIN"] = login
    env["ISO_CAPTURE_PROVISION_PASSWORD"] = password
    script = '''\
import os
login = os.environ["ISO_CAPTURE_PROVISION_LOGIN"]
if env["res.users"].sudo().search_count([("login", "=", login)]):
    raise ValueError("Generated login already exists")
group = env.ref("iso_management.group_iso_capture_worker")
companies = env["res.company"].sudo().search([])
user = env["res.users"].sudo().with_context(no_reset_password=True, tracking_disable=True).create({
    "name": "ISO screenshot worker", "login": login,
    "password": os.environ["ISO_CAPTURE_PROVISION_PASSWORD"],
    "group_ids": [(6, 0, [group.id])],
    "company_id": env.company.id, "company_ids": [(6, 0, companies.ids)],
})
env.cr.commit()
print("Capture account created", user.id)
'''
    command = ["docker", "compose", "exec", "-T", "-e", "ODOO_RC=/tmp/odoo.conf", "-e", "ISO_CAPTURE_PROVISION_LOGIN", "-e", "ISO_CAPTURE_PROVISION_PASSWORD", "odoo", "/entrypoint.sh", "odoo", "shell", "--config=/tmp/odoo.conf", "-d", entries.get("ISO_CAPTURE_DB", "sales") or "sales", "--no-http"]
    result = subprocess.run(command, input=script, text=True, capture_output=True, env=env, cwd=ROOT)
    if result.returncode:
        raise SystemExit("Could not create capture account; check Odoo logs.")
    replacements = {"ISO_CAPTURE_LOGIN": login, "ISO_CAPTURE_PASSWORD": password}
    lines = [line for line in lines if not any(line.startswith(key + "=") for key in replacements)]
    lines.extend(f"{key}={value}" for key, value in replacements.items())
    ENV_FILE.write_text("\n".join(lines) + "\n", encoding="utf-8")
    print("Capture account configured in .env.")


if __name__ == "__main__":
    main()
