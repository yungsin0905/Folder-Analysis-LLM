"""
seo_agent.py
每天自动运行的 SEO 优化 Agent

重要：本脚本只会读取/修改 index.html 的 <head> 区域内的 meta 标签、
title、canonical、Open Graph、结构化数据（JSON-LD）。
绝不会碰 <body>、<style>、<script> 等任何影响网站版面/设计/功能的内容。

流程：
1. 读取本地 index.html 的 <head> 内容
2. 把内容 + 竞品 SEO 打法参考，丢给本地 LM Studio 分析，生成新的 meta 建议
3. 只替换 <head> 里的 SEO 相关标签
4. 自动 git add + commit + push 到 GitHub
5. SSH 登录服务器，执行 git pull，让网站生效
"""

import os
import re
import json
import subprocess
import datetime
from openai import OpenAI
import paramiko

# ------------------------------------------------------------------
# 配置区 —— 请按你自己的实际情况修改这几项
# ------------------------------------------------------------------
PROJECT_DIR = r"C:\Users\user\Desktop\Website"          # 本地项目文件夹路径
INDEX_HTML_PATH = os.path.join(PROJECT_DIR, "index.html")
LOG_PATH = os.path.join(PROJECT_DIR, "llm","seo_agent_log.txt")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
LM_MODEL_NAME = "openai/gpt-oss-20b"                    # 跟你之前 backend.py 保持一致

SITE_URL = "https://docbot.makerkluang.com/"

SSH_HOST = "makerkluang.com"
SSH_PORT = 55000
SSH_USER = "makerklu"
SSH_KEY_PATH = r"C:\Users\user\.ssh"             # ← 改成你实际的私钥文件路径
REMOTE_REPO_PATH = "/home2/makerklu/docbot.makerkluang.com"

client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")


def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------
# 1. 读取现有 <head> 内容
# ------------------------------------------------------------------
def read_head_section(html: str) -> str:
    match = re.search(r"<head>(.*?)</head>", html, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("找不到 <head> 区域，请检查 index.html 结构是否被改动过")
    return match.group(1)


# ------------------------------------------------------------------
# 2. 调用本地 LLM，只生成 SEO meta 建议（JSON 格式，不碰版面）
# ------------------------------------------------------------------
COMPETITOR_CHECKLIST = """
参考同类 AI 文档分析工具（Docsumo / Nanonets / Parseur）常见的 SEO 打法：
1. 标题和描述要包含具体关键词（AI folder analyzer, document data extraction, LLM document parsing 等）
2. 描述要讲清楚具体使用场景/痛点，而不是空泛的"强大工具"这种话术
3. 需要 Open Graph 和 Twitter Card 标签，方便分享时展示
4. 需要 canonical 链接，避免重复内容问题
5. 需要 JSON-LD 结构化数据（schema.org WebApplication 类型）
"""

def generate_seo_suggestions(current_head: str) -> dict:
    prompt = f"""
你是一个网站 SEO 专家。下面是网站当前 <head> 区域的内容：

{current_head}

{COMPETITOR_CHECKLIST}

网站背景：这是一个 AI 驱动的文件夹/文档分析工具，用户上传一个文件夹后，
系统会自动用 LLM 分析里面每一份文件（PDF/Word/Excel/图片），提取关键字段，
最后导出成 CSV 文件下载。网址是：{SITE_URL}

请只返回下面这些字段的 JSON（不要输出任何其他文字、不要 markdown 代码块）：
{{
  "title": "...",
  "description": "...",
  "keywords": "...",
  "og_title": "...",
  "og_description": "..."
}}

要求：
- title 控制在 60 字符以内
- description 控制在 150-160 字符以内
- 语言使用英文（网站界面是英文）
- 不要提及任何网站上没有出现过的功能（不要瞎编）
"""
    response = client.chat.completions.create(
        model=LM_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a professional SEO copywriter. Only output valid JSON, nothing else."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    content = response.choices[0].message.content.strip()
    content = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
    return json.loads(content)


# ------------------------------------------------------------------
# 3. 把建议写回 <head>，绝不碰 <body>/<style>/<script>
# ------------------------------------------------------------------
def apply_seo_head(html: str, seo: dict) -> str:
    head_match = re.search(r"(<head>)(.*?)(</head>)", html, re.DOTALL | re.IGNORECASE)
    if not head_match:
        raise ValueError("找不到 <head> 区域")

    head_content = head_match.group(2)

    # 替换 <title>
    if re.search(r"<title>.*?</title>", head_content, re.IGNORECASE | re.DOTALL):
        head_content = re.sub(
            r"<title>.*?</title>",
            f"<title>{seo['title']}</title>",
            head_content,
            flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        head_content = f"<title>{seo['title']}</title>\n" + head_content

    # 移除脚本之前跑过留下的旧 SEO 标签，避免越堆越多
    seo_tag_pattern = re.compile(
        r'\s*<meta name="description"[^>]*>'
        r'|\s*<meta name="keywords"[^>]*>'
        r'|\s*<meta property="og:[^"]*"[^>]*>'
        r'|\s*<meta name="twitter:[^"]*"[^>]*>'
        r'|\s*<link rel="canonical"[^>]*>'
        r'|\s*<script type="application/ld\+json">.*?</script>',
        re.IGNORECASE | re.DOTALL,
    )
    head_content = seo_tag_pattern.sub("", head_content)

    seo_block = f"""
    <meta name="description" content="{seo['description']}">
    <meta name="keywords" content="{seo['keywords']}">
    <link rel="canonical" href="{SITE_URL}">
    <meta property="og:title" content="{seo['og_title']}">
    <meta property="og:description" content="{seo['og_description']}">
    <meta property="og:type" content="website">
    <meta property="og:url" content="{SITE_URL}">
    <meta name="twitter:card" content="summary_large_image">
    <script type="application/ld+json">
    {{
      "@context": "https://schema.org",
      "@type": "WebApplication",
      "name": "{seo['title']}",
      "url": "{SITE_URL}",
      "applicationCategory": "BusinessApplication",
      "description": "{seo['description']}"
    }}
    </script>
"""

    new_head_content = head_content.rstrip() + "\n" + seo_block
    new_html = html[: head_match.start(2)] + new_head_content + html[head_match.end(2):]
    return new_html


# ------------------------------------------------------------------
# 4. Git 自动提交 + 推送到 GitHub
# ------------------------------------------------------------------
def git_commit_and_push():
    today = datetime.date.today().isoformat()
    commands = [
        ["git", "add", "index.html"],
        ["git", "commit", "-m", f"Automated SEO update: {today}"],
        ["git", "push"],
    ]
    for cmd in commands:
        result = subprocess.run(cmd, cwd=PROJECT_DIR, capture_output=True, text=True)
        log(f"$ {' '.join(cmd)}\n{result.stdout}{result.stderr}")
        if result.returncode != 0 and "nothing to commit" not in result.stdout:
            raise RuntimeError(f"Git 命令失败: {' '.join(cmd)}\n{result.stderr}")


# ------------------------------------------------------------------
# 5. SSH 登录服务器，执行 git pull，让网站真正更新
# ------------------------------------------------------------------
def ssh_pull_remote():
    ssh = paramiko.SSHClient()
    ssh.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    ssh.connect(
        hostname=SSH_HOST,
        port=SSH_PORT,
        username=SSH_USER,
        key_filename=SSH_KEY_PATH,
    )
    command = f"cd {REMOTE_REPO_PATH} && git pull"
    stdin, stdout, stderr = ssh.exec_command(command)
    out = stdout.read().decode()
    err = stderr.read().decode()
    log(f"$ ssh git pull\n{out}{err}")
    ssh.close()


# ------------------------------------------------------------------
# 主流程
# ------------------------------------------------------------------
def main():
    log("===== SEO Agent 开始运行 =====")
    try:
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()

        # 先备份原文件，出问题随时能恢复
        backup_path = INDEX_HTML_PATH + f".backup-{datetime.date.today().isoformat()}"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"已备份原文件到 {backup_path}")

        current_head = read_head_section(html)
        seo = generate_seo_suggestions(current_head)
        log(f"LLM 生成的 SEO 建议:\n{json.dumps(seo, ensure_ascii=False, indent=2)}")

        new_html = apply_seo_head(html, seo)

        with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(new_html)
        log("已写回 index.html（只有 <head> 区域有变化，版面/样式/脚本完全未动）")

        git_commit_and_push()
        ssh_pull_remote()

        log("===== SEO Agent 运行完成 =====")
    except Exception as e:
        log(f"❌ 运行出错: {e}")
        raise


if __name__ == "__main__":
    main()