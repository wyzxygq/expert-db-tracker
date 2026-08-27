# -*- coding: utf-8 -*-
"""本机兜底运行器（国内网络直连，与 GitHub Actions 双保险）。

流程：
    1. 从 GitHub 拉取线上最新 data.json / state.json（避免覆盖云端 Actions 的更新）
    2. 运行 fetch.py 完成抓取 -> 关键词筛选 -> 去重 -> 微信推送(PushPlus)
    3. 对比线上内容，有实质变化才通过 GitHub API 推回（带 sha，冲突时记录留待下次重试）

用法：
    python scripts/local_runner.py

配置：与脚本同目录的 .local_config.json（勿提交到 GitHub，已在 .gitignore 中）：
    {
        "gh_token": "github_pat_xxx 或 ghp_xxx",
        "repo": "wyzxygq/expert-db-tracker",
        "branch": "main",
        "pushplus_token": "pushplus 一对一定推 token (可选)",
        "serverchan_sendkey": "Server酱 SendKey, https://sct.ftqq.com (可选)"
    }

日志：项目根目录 local_run.log（追加模式）。
"""
import base64
import json
import os
import subprocess
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

CST = timezone(timedelta(hours=8))
HERE = os.path.dirname(os.path.abspath(__file__))
BASE_DIR = os.path.dirname(HERE)
CONFIG_FILE = os.path.join(HERE, ".local_config.json")
LOG_FILE = os.path.join(BASE_DIR, "local_run.log")

DATA_FILE = os.path.join(BASE_DIR, "data.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")


def log(msg):
    line = "[%s] %s" % (datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"), msg)
    print(line)
    with open(LOG_FILE, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def api(path, method="GET", body=None, token=None):
    url = "https://api.github.com/repos/%s" % path
    headers = {"Accept": "application/vnd.github.v3+json", "User-Agent": "local-runner"}
    if token:
        headers["Authorization"] = "token %s" % token
    data = None
    if body is not None:
        data = json.dumps(body).encode("utf-8")
        headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, method=method, headers=headers)
    with urllib.request.urlopen(req, timeout=30) as resp:
        return resp.read()


def fetch_file(path, token):
    """下载仓库文件内容，返回 (content_str, sha)；不存在返回 (None, None)。"""
    try:
        raw = api(path, token=token)
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return None, None
        raise
    d = json.loads(raw)
    return base64.b64decode(d["content"]).decode("utf-8"), d["sha"]


def push_file(full_path, content, sha, token, message):
    body = {
        "message": message,
        "content": base64.b64encode(content.encode("utf-8")).decode("utf-8"),
        "branch": "main",
    }
    if sha:
        body["sha"] = sha
    raw = api(full_path, method="PUT", body=body, token=token)
    return json.loads(raw)["content"]["sha"]


def strip_updated(content):
    """去掉 updated_at 字段再比较，0 新增时避免产生无意义 commit。"""
    try:
        d = json.loads(content)
        d.pop("updated_at", None)
        return json.dumps(d, ensure_ascii=False, sort_keys=True)
    except Exception:
        return content


def main():
    with open(CONFIG_FILE, "r", encoding="utf-8") as f:
        cfg = json.load(f)
    gh_token = cfg["gh_token"].strip()
    pushplus = cfg.get("pushplus_token", "").strip()
    serverchan = cfg.get("serverchan_sendkey", "").strip()
    branch = cfg.get("branch", "main")
    prefix = cfg["repo"] + "/contents/"

    log("========== 本机兜底采集开始 ==========")

    # 1) 同步线上最新状态，避免覆盖云端 Actions 刚写入的内容
    for fname in ("data.json", "state.json"):
        content, sha = fetch_file(prefix + fname, gh_token)
        if content is None:
            log("[提示] 线上无 %s，将作为首次运行" % fname)
            continue
        with open(os.path.join(BASE_DIR, fname), "w", encoding="utf-8") as f:
            f.write(content)
        log("已同步线上 %s (sha=%s...)" % (fname, sha[:10]))

    # 2) 运行采集（fetch.py 负责抓取/去重/写文件/推送通知）
    env = dict(os.environ)
    env["PUSHPLUS_TOKEN"] = pushplus
    env["SERVERCHAN_SENDKEY"] = serverchan
    env["PYTHONIOENCODING"] = "utf-8"
    cmd = [sys.executable, os.path.join(HERE, "fetch.py")]
    try:
        r = subprocess.run(cmd, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=300)
        out = (r.stdout or "") + (r.stderr or "")
    except subprocess.TimeoutExpired:
        log("[错误] 采集超时(>5分钟)，本次终止")
        out = ""
    except Exception as e:
        log("[错误] 采集进程异常: %s" % e)
        out = ""
    for line in out.splitlines():
        if line.strip():
            log("  " + line.strip())

    # 3) 有实质变化才推回 GitHub
    for fname in ("data.json", "state.json"):
        local_path = os.path.join(BASE_DIR, fname)
        if not os.path.exists(local_path):
            continue
        with open(local_path, "r", encoding="utf-8") as f:
            new_content = f.read()
        remote, sha = fetch_file(prefix + fname, gh_token)
        if remote is not None and strip_updated(remote) == strip_updated(new_content):
            log("%s 无实质变化，不推送" % fname)
            continue
        try:
            new_sha = push_file(prefix + fname, new_content, sha, gh_token,
                                "local-fallback: 更新 %s" % fname)
            log("已推送 %s (sha=%s...)" % (fname, new_sha[:10]))
        except urllib.error.HTTPError as e:
            body = ""
            try:
                body = e.read().decode("utf-8", errors="ignore")[:200]
            except Exception:
                pass
            log("[冲突] %s 推送失败 HTTP %s %s（云端可能在同时更新，下次运行自动重试）"
                % (fname, e.code, body))

    log("========== 本机兜底采集结束 ==========")


if __name__ == "__main__":
    main()
