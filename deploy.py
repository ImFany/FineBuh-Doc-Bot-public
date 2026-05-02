"""Deployment script for FineBuh-Doc-Bot to production VPS."""
import os
import sys
import paramiko
from pathlib import Path
from dotenv import load_dotenv

# Load environment variables
load_dotenv('.env.local')
load_dotenv('.env')

HOST = os.getenv('DEPLOY_HOST') or os.getenv('VPS_HOST')
USER = os.getenv('DEPLOY_USER') or os.getenv('VPS_USER', 'root')
PASSWORD = os.getenv('DEPLOY_PASSWORD') or os.getenv('VPS_PASS')
REMOTE_DIR = os.getenv('DEPLOY_REMOTE_DIR', '/opt/docflow-bot')

FILES_TO_DEPLOY = [
    ('bot/main.py', f'{REMOTE_DIR}/bot/main.py'),
    ('bot/parser.py', f'{REMOTE_DIR}/bot/parser.py'),
    ('bot/generator.py', f'{REMOTE_DIR}/bot/generator.py'),
    ('bot/db.py', f'{REMOTE_DIR}/bot/db.py'),
    ('bot/config.py', f'{REMOTE_DIR}/bot/config.py'),
    ('bot/log_utils.py', f'{REMOTE_DIR}/bot/log_utils.py'),
    ('bot/num2words_ru.py', f'{REMOTE_DIR}/bot/num2words_ru.py'),
    ('requirements.txt', f'{REMOTE_DIR}/requirements.txt'),
]

def run_command(ssh, cmd, check=True):
    print(f"\n$ {cmd}")
    _, stdout, stderr = ssh.exec_command(cmd, timeout=120)
    out = stdout.read().decode().strip()
    err = stderr.read().decode().strip()
    if out: print(out)
    if err and check: print("[stderr]", err)
    rc = stdout.channel.recv_exit_status()
    if check and rc != 0:
        raise RuntimeError(f"Command failed (rc={rc})")
    return out, err, rc

def main():
    print("=" * 70)
    print("FineBuh-Doc-Bot Deployment to VPS")
    print("=" * 70)
    
    if not HOST or not USER or not PASSWORD:
        print("❌ Missing credentials in .env.local or .env")
        sys.exit(1)
    
    try:
        ssh = paramiko.SSHClient()
        ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
        print(f"\n Connecting to {USER}@{HOST}...")
        ssh.connect(HOST, username=USER, password=PASSWORD, timeout=15)
        print("✓ Connected\n")
        
        # Upload files
        print("📤 Uploading files...")
        sftp = ssh.open_sftp()
        for local, remote in FILES_TO_DEPLOY:
            if not Path(local).exists():
                print(f"  ⚠️  {local} not found")
                continue
            try:
                remote_dir = str(Path(remote).parent)
                try:
                    sftp.stat(remote_dir)
                except:
                    run_command(ssh, f"mkdir -p {remote_dir}")
                sftp.put(local, remote)
                print(f"  ✓ {local}")
            except Exception as e:
                print(f"  ❌ {local}: {e}")
        sftp.close()
        
        # Update dependencies
        print("\n📦 Updating dependencies...")
        venv_pip = f"{REMOTE_DIR}/venv/bin/pip"
        run_command(ssh, f"{venv_pip} install -U pip", check=False)
        run_command(ssh, f"{venv_pip} install -r {REMOTE_DIR}/requirements.txt")
        
        # Restart service
        print("\n🔄 Restarting service...")
        run_command(ssh, f"rm -rf {REMOTE_DIR}/bot/__pycache__", check=False)
        run_command(ssh, "systemctl restart docflow-bot", check=False)
        
        # Show logs
        print("\n📋 Recent logs:")
        out, _, _ = run_command(ssh, "journalctl -u docflow-bot -n 15 --no-pager", check=False)
        
        print("\n" + "=" * 70)
        print("✅ DEPLOYMENT COMPLETE!")
        print("=" * 70)
        ssh.close()
        
    except Exception as e:
        print(f"\n❌ Error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
