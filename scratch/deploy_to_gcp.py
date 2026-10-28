import subprocess, sys

sys.stdout.reconfigure(encoding='utf-8')

def run_ssh(remote_cmd):
    cmd = [
        'ssh', '-i', r'C:\Users\tenso\.ssh\gcp_agent_key',
        '-o', 'StrictHostKeyChecking=no',
        'tensonyin@35.212.194.139',
        remote_cmd
    ]
    res = subprocess.run(cmd, capture_output=True, text=True, encoding='utf-8')
    if res.stdout:
        print("[STDOUT]\n" + res.stdout)
    if res.stderr:
        print("[STDERR]\n" + res.stderr)
    return res

if __name__ == '__main__':
    print("=== Deploying to GCP ===")
    deploy_cmd = """
cd /home/tensonyin/cogni-scaffold && \\
git pull origin main && \\
sudo docker build -t cogni-scaffold-app:latest . && \\
sudo docker stop cogni-scaffold && \\
sudo docker rm cogni-scaffold && \\
sudo docker run -d --name cogni-scaffold --restart unless-stopped -p 8501:8501 --env-file .env -v /home/tensonyin/cogni-scaffold/data:/app/data cogni-scaffold-app:latest && \\
sleep 5 && \\
sudo docker ps | grep cogni-scaffold && \\
curl -s http://127.0.0.1:8501/ | grep -o 'feedbackModal' && \\
curl -s http://127.0.0.1:8501/ | grep -o 'v2.8.0' && \\
echo 'GCP deployment verified successfully!'
"""
    res = run_ssh(deploy_cmd)
    if res.returncode == 0:
        print("=== Deployment finished successfully! ===")
    else:
        print("=== Deployment failed with code:", res.returncode)
