"""One-shot deployment script for forwarder.py to VPS."""
import paramiko
import time

HOST = "178.208.91.83"
USER = "root"
PASS = "MQbs5xN8Pv"
REMOTE_DIR = "/opt/tg-forwarder"

FORWARDER_SRC = "forwarder.py"

SYSTEMD_UNIT = """\
[Unit]
Description=Telegram Keyword Forwarder
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/opt/tg-forwarder
ExecStart=/usr/bin/python3 /opt/tg-forwarder/forwarder.py
Restart=always
RestartSec=10
StandardOutput=journal
StandardError=journal
Environment=TG_TARGET_CHANNEL=NF_alarm

[Install]
WantedBy=multi-user.target
"""


def run(ssh, cmd, *, check=True):
    print(f"\n$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode()
    err = stderr.read().decode()
    if out:
        print(out.rstrip())
    if err:
        print("[stderr]", err.rstrip())
    rc = stdout.channel.recv_exit_status()
    if check and rc != 0:
        raise RuntimeError(f"Command failed (rc={rc}): {cmd}")
    return out, err, rc


def main():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    print(f"Connecting to {HOST}...")
    ssh.connect(HOST, username=USER, password=PASS, timeout=15)
    print("Connected.\n")

    # 1. System update + Python + pip
    run(ssh, "apt-get update -qq")
    run(ssh, "apt-get install -y -qq python3 python3-pip python3-venv")
    out, _, _ = run(ssh, "python3 --version")
    print("Python:", out.strip())

    # 2. Working directory
    run(ssh, f"mkdir -p {REMOTE_DIR}")

    # 3. Upload forwarder.py via SFTP
    sftp = ssh.open_sftp()
    remote_path = f"{REMOTE_DIR}/forwarder.py"
    sftp.put(FORWARDER_SRC, remote_path)
    print(f"\nUploaded forwarder.py -> {remote_path}")

    # 4. Install telethon
    run(ssh, f"pip3 install -q telethon")
    out, _, _ = run(ssh, "pip3 show telethon | grep Version")
    print("Telethon:", out.strip())

    # 5. Write systemd unit
    unit_content = SYSTEMD_UNIT.replace('"', '\\"')
    run(ssh, f'cat > /etc/systemd/system/tg-forwarder.service << \'EOF\'\n{SYSTEMD_UNIT}EOF')

    # 6. Enable service (but don't start yet — need auth first)
    run(ssh, "systemctl daemon-reload")
    run(ssh, "systemctl enable tg-forwarder.service")

    sftp.close()
    ssh.close()

    print("\n" + "="*60)
    print("ДЕПЛОЙ ЗАВЕРШЁН.")
    print("="*60)
    print("""
Следующий шаг — первичная авторизация Telethon (один раз).

Подключитесь к серверу вручную:
  ssh root@178.208.91.83

Затем запустите:
  cd /opt/tg-forwarder
  python3 forwarder.py

Введите номер телефона и код из Telegram.
После успешного старта нажмите Ctrl+C.

Потом запускайте сервис:
  systemctl start tg-forwarder
  systemctl status tg-forwarder
""")


if __name__ == "__main__":
    main()
