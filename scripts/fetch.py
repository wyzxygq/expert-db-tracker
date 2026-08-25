# -*- coding: utf-8 -*-
"""专家库动态采集器：每日抓取公告页 -> 关键词筛选 -> 去重 -> 生成 data.json -> 推送微信(PushPlus)。

用法:
    python scripts/fetch.py

环境变量(可选):
    PUSHPLUS_TOKEN  微信推送 token, 在 https://www.pushplus.plus 微信扫码登录后获取。
                    GitHub Actions 中通过仓库 Secret 注入。
"""
import hashlib
import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone
from html import unescape

BASE_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DATA_FILE = os.path.join(BASE_DIR, "data.json")
STATE_FILE = os.path.join(BASE_DIR, "state.json")
SOURCES_FILE = os.path.join(BASE_DIR, "scripts", "sources.json")

CST = timezone(timedelta(hours=8))
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/124.0 Safari/537.36")

LINK_RE = re.compile(
    r'<a[^>]+href=["\']?([^"\'>\s]+)["\']?[^>]*>([^<]{4,120})</a>', re.I)
# 部分政府网站(如武汉市公共资源交易中心)公告链接放在 onclick="window.open('...')" 中
ONCLICK_RE = re.compile(
    r'<a[^>]+onclick=["\']\s*window\.open\(["\']([^"\']+)["\']\)[^>]*>([^<]{4,120})</a>',
    re.I)


def log(msg):
    print("[%s] %s" % (datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S"), msg))


def fetch_html(url, timeout=20):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        raw = resp.read()
    for enc in ("utf-8", "gbk"):
        try:
            return raw.decode(enc)
        except (UnicodeDecodeError, LookupError):
            continue
    return raw.decode("utf-8", errors="ignore")


def resolve_url(href, base_url):
    """把相对/协议相对链接转为绝对地址。"""
    if href.startswith("//"):
        return "https:" + href
    if href.startswith("/"):
        return base_url.rstrip("/") + href
    if href.startswith("http"):
        return href
    return base_url.rstrip("/") + "/" + href


def extract_links(html, base_url):
    """提取页面内全部<a>标题与链接(兼容 onclick window.open 与相对路径)。"""
    out, seen = [], set()
    # 1) onclick 里的真实链接优先(如武汉交易中心)
    for href, text in ONCLICK_RE.findall(html):
        text = unescape(re.sub(r"\s+", " ", text)).strip()
        if not text:
            continue
        url = resolve_url(href, base_url)
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((text, url))
    # 2) 普通 <a href> 链接
    for href, text in LINK_RE.findall(html):
        text = unescape(re.sub(r"\s+", " ", text)).strip()
        if not text:
            continue
        if href == "#" or href.startswith("javascript"):
            continue
        url = resolve_url(href, base_url)
        key = url.split("#")[0]
        if key in seen:
            continue
        seen.add(key)
        out.append((text, url))
    return out


def match_keywords(title, keywords):
    if not keywords:
        return True
    return any(k in title for k in keywords)


def make_id(source_id, link):
    return hashlib.md5(("%s:%s" % (source_id, link)).encode("utf-8")).hexdigest()


def load_json(path, default):
    if os.path.exists(path):
        try:
            with open(path, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            return default
    return default


def save_json(path, obj):
    with open(path, "w", encoding="utf-8") as f:
        json.dump(obj, f, ensure_ascii=False, indent=2)


def demo_records(source):
    """demo 源: 首次运行生成示例公告, 便于测试全流程。"""
    now = datetime.now(CST)
    return [
        {
            "id": make_id(source["id"], "demo-1"),
            "date": now.strftime("%Y-%m-%d"),
            "province": source["province"],
            "title": "示例：XX省综合评标专家库公开征集入库专家公告（第一批）",
            "source": source["name"],
            "link": "https://example.gov.cn/notice/demo-1",
            "deadline": (now + timedelta(days=20)).strftime("%Y-%m-%d"),
        },
        {
            "id": make_id(source["id"], "demo-2"),
            "date": now.strftime("%Y-%m-%d"),
            "province": source["province"],
            "title": "示例：XX省安全生产专家库申报工作启动",
            "source": source["name"],
            "link": "https://example.gov.cn/notice/demo-2",
            "deadline": "",
        },
    ]


def scan_source(source, state):
    """抓取单个源, 返回新增公告列表。"""
    seen = state.setdefault("seen", {})
    fresh = []

    if source.get("demo"):
        for rec in demo_records(source):
            if rec["id"] not in seen:
                fresh.append(rec)
        log("demo 源: 生成 %d 条示例" % len(fresh))
        return fresh

    url = source.get("url", "")
    if not url:
        return fresh
    log("抓取 %s (%s) ..." % (source["name"], url))
    try:
        html = fetch_html(url)
    except urllib.error.HTTPError as e:
        log("  [失败] HTTP %s" % e.code)
        return fresh
    except Exception as e:
        log("  [失败] %s" % e)
        return fresh

    for title, link in extract_links(html, url):
        if not match_keywords(title, source.get("keywords", [])):
            continue
        rid = make_id(source["id"], link)
        if rid in seen:
            continue
        fresh.append({
            "id": rid,
            "date": datetime.now(CST).strftime("%Y-%m-%d"),
            "province": source.get("province", ""),
            "title": title,
            "source": source["name"],
            "link": link,
            "deadline": "",
        })
    log("  命中新增 %d 条" % len(fresh))
    return fresh


def push_wechat(new_records):
    token = os.environ.get("PUSHPLUS_TOKEN", "").strip()
    if not token:
        log("未设置 PUSHPLUS_TOKEN, 跳过微信推送 (本地测试属正常)")
        return
    if not new_records:
        log("无新增, 不推送")
        return
    items = "".join(
        '<p><b>[%s]</b> <a href="%s">%s</a><br><span style="color:#888">%s · %s</span></p>'
        % (r["province"] or "未分类", r["link"], r["title"], r["source"], r["date"])
        for r in new_records[:20])
    payload = {
        "token": token,
        "title": "专家库动态：今日新增 %d 条" % len(new_records),
        "content": items,
        "template": "html",
    }
    req = urllib.request.Request(
        "https://www.pushplus.plus/send",
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=15) as resp:
            body = resp.read().decode("utf-8", errors="ignore")
        log("推送结果: %s" % body[:200])
    except Exception as e:
        log("推送失败: %s" % e)


def main():
    sources = load_json(SOURCES_FILE, {}).get("sources", [])
    if not sources:
        log("sources.json 中没有数据源, 退出")
        sys.exit(1)

    data = load_json(DATA_FILE, {"updated_at": "", "records": []})
    state = load_json(STATE_FILE, {"seen": {}})

    existing_ids = {r["id"] for r in data.get("records", [])}
    new_records = []
    for src in sources:
        fresh = scan_source(src, state)
        for r in fresh:
            if r["id"] not in existing_ids:
                new_records.append(r)
                state["seen"][r["id"]] = True

    if new_records:
        data["records"] = new_records + data.get("records", [])
        # 按日期倒序
        data["records"].sort(key=lambda r: r.get("date", ""), reverse=True)
        # 总量上限 500, 防止无限膨胀
        data["records"] = data["records"][:500]

    data["updated_at"] = datetime.now(CST).strftime("%Y-%m-%d %H:%M:%S")
    save_json(DATA_FILE, data)
    save_json(STATE_FILE, state)

    log("本次新增 %d 条, 当前共 %d 条" % (len(new_records), len(data["records"])))
    push_wechat(new_records)


if __name__ == "__main__":
    main()
