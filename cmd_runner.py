import os, json, time, subprocess, base64, urllib.request
from datetime import datetime, timezone
from dotenv import load_dotenv

load_dotenv()

GH_TOKEN = os.environ.get("GITHUB_TOKEN", "")
GH_USER = os.environ.get("GH_USER", "")
REPO = os.environ.get("GH_REPO", "")
PENDING_PATH = "cmds/pending.json"
RESULT_PATH = "cmds/result.json"
POLL_INTERVAL = 5

def gh_get(path):
    url = f"https://api.github.com/repos/{GH_USER}/{REPO}/contents/{path}"
    req = urllib.request.Request(url)
    req.add_header("Authorization", f"token {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def gh_put(path, content, sha, message):
    url = f"https://api.github.com/repos/{GH_USER}/{REPO}/contents/{path}"
    encoded = base64.b64encode(json.dumps(content, ensure_ascii=False).encode()).decode()
    data = json.dumps({"message": message, "content": encoded, "sha": sha}).encode()
    req = urllib.request.Request(url, data=data, method="PUT")
    req.add_header("Authorization", f"token {GH_TOKEN}")
    req.add_header("Accept", "application/vnd.github.v3+json")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())

def get_file(path):
    result = gh_get(path)
    content = base64.b64decode(result["content"]).decode()
    return json.loads(content), result["sha"]

def main():
    last_id = None
    print("cmd_runner started", flush=True)
    while True:
        try:
            pending, _ = get_file(PENDING_PATH)
            cmd_id = pending.get("id")
            cmd = pending.get("cmd", "")
            if cmd_id and cmd_id != last_id:
                last_id = cmd_id
                print(f"Executing [{cmd_id}]: {cmd}", flush=True)
                try:
                    proc = subprocess.run(
                        cmd, shell=True, capture_output=True,
                        text=True, timeout=120
                    )
                    stdout = proc.stdout[-3000:] if proc.stdout else ""
                    stderr = proc.stderr[-1000:] if proc.stderr else ""
                    rc = proc.returncode
                except subprocess.TimeoutExpired:
                    stdout, stderr, rc = "", "timeout", -1
                _, sha = get_file(RESULT_PATH)
                result = {
                    "id": cmd_id,
                    "cmd": cmd,
                    "stdout": stdout,
                    "stderr": stderr,
                    "returncode": rc,
                    "ts": datetime.now(timezone.utc).isoformat()
                }
                gh_put(RESULT_PATH, result, sha, f"result: {cmd_id}")
                print(f"Done [{cmd_id}] rc={rc}", flush=True)
        except Exception as e:
            print(f"Error: {e}", flush=True)
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    main()
