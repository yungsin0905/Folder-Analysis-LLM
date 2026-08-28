"""
seo_agent.py —— 每日自动 SEO Agent（完整版）

覆盖六项需求：
1+2. 关键词研究 + AI 分析关键词 —— 基于 LLM 推理相关关键词（没有付费关键词工具，
     不编造搜索量数字，只给"为什么相关"的判断），每天跑。
3. AI 自动内容优化 —— 沿用关键词推理结果，重写 <head> 里的 meta 标签，每天跑。
4. AI 自动 SEO 审计 —— 检查 title/description 长度、canonical、h1、sitemap/robots
     是否可正常访问，每天跑，结果写进日志。
5. AI 自动结构化数据 —— 在 WebApplication schema 之外，额外生成 FAQPage schema
     （从页面现有 FAQ 区块自动提取问答），每天跑。
6. 内容差距分析 —— 对比同类竞品页面内容，找出本站未覆盖的主题，只在每周一跑
     （避免每天重复抓取竞品页面、内容本身也不会天天变化）。

重要：本脚本只修改 index.html 的 <head> 区域（meta 标签 / 结构化数据）。
绝不会碰 <body> 的可见内容、<style>、<script>，网站版面/设计/功能完全不受影响。
第 6 项内容差距分析只生成"建议清单"记录在日志里，不会自动改动网站内容，
需要人工看过觉得合适后再手动采纳。

流程：读取网站内容 → 关键词推理 → 生成 meta 建议 → 生成 FAQ 结构化数据
     → 写回 index.html → SEO 审计 → （周一）内容差距分析 → git push
     （服务器端由 cPanel Cron Job 独立执行 git pull，本脚本不处理这一步）
"""

import os
import re
import json
import subprocess
import datetime
import requests
from openai import OpenAI
from bs4 import BeautifulSoup

# ------------------------------------------------------------------
# 配置区 —— 请按你自己的实际情况修改这几项
# ------------------------------------------------------------------
PROJECT_DIR = r"C:\Users\user\Desktop\Website"
INDEX_HTML_PATH = os.path.join(PROJECT_DIR, "index.html")
LOG_PATH = os.path.join(PROJECT_DIR, "llm", "seo_agent_log.txt")

LM_STUDIO_URL = "http://127.0.0.1:1234/v1"
LM_MODEL_NAME = "openai/gpt-oss-20b"

SITE_URL = "https://docbot.makerkluang.com/"

# 同类竞品，用于第 6 项内容差距分析（可以自行增减）
COMPETITOR_URLS = [
    "https://www.docsumo.com/",
    "https://nanonets.com/",
    "https://parseur.com/",
]

client = OpenAI(base_url=LM_STUDIO_URL, api_key="lm-studio")


def log(msg: str):
    timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    line = f"[{timestamp}] {msg}"
    print(line)
    with open(LOG_PATH, "a", encoding="utf-8") as f:
        f.write(line + "\n")


# ------------------------------------------------------------------
# 基础读取函数
# ------------------------------------------------------------------
def read_head_section(html: str) -> str:
    match = re.search(r"<head>(.*?)</head>", html, re.DOTALL | re.IGNORECASE)
    if not match:
        raise ValueError("找不到 <head> 区域，请检查 index.html 结构")
    return match.group(1)


def read_body_text(html: str) -> str:
    """粗略提取 <body> 内的可见文字，用于关键词推理 / 内容差距分析，不用于改写。"""
    body_match = re.search(r"<body>(.*?)</body>", html, re.DOTALL | re.IGNORECASE)
    body = body_match.group(1) if body_match else html
    text = re.sub(r"<script.*?</script>", "", body, flags=re.DOTALL | re.IGNORECASE)
    text = re.sub(r"<[^>]+>", " ", text)
    text = re.sub(r"\s+", " ", text).strip()
    return text[:3000]


# ------------------------------------------------------------------
# 1+2. 关键词研究 + AI 分析关键词（基于推理，不编造搜索量数字）
# ------------------------------------------------------------------
def generate_keyword_strategy(body_text: str) -> dict:
    prompt = f"""
你是SEO关键词策略专家。下面是网站目前的可见文字内容：

{body_text}

网站背景：AI 驱动的文件夹/文档分析工具，用户上传文件夹，系统自动用 LLM 解析
PDF/Word/Excel/图片里的内容，提取关键字段，导出 CSV。

参考同类工具（Docsumo、Nanonets、Parseur）常用的市场语言和使用场景，推理出一批
与本站高度相关的关键词/短语。不要编造具体搜索量数字（我们没有付费关键词工具），
只给出"为什么相关"的简短理由。

只返回 JSON，不要输出其他文字：
{{
  "high_priority": ["...", "..."],
  "medium_priority": ["...", "..."],
  "reasoning": "一两句话说明推理依据"
}}
"""
    response = client.chat.completions.create(
        model=LM_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are an SEO keyword strategist. Only output valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    content = response.choices[0].message.content.strip()
    content = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
    return json.loads(content)


# ------------------------------------------------------------------
# 3. AI 自动内容优化（生成 meta 建议，接入关键词推理结果）
# ------------------------------------------------------------------
def generate_seo_suggestions(current_head: str, keyword_strategy: dict) -> dict:
    prompt = f"""
你是网站 SEO 专家。下面是网站当前 <head> 区域的内容：

{current_head}

关键词策略团队给出的高优先级关键词：{keyword_strategy.get('high_priority', [])}
中优先级关键词：{keyword_strategy.get('medium_priority', [])}
推理依据：{keyword_strategy.get('reasoning', '')}

网站背景：AI 驱动的文件夹/文档分析工具，用户上传文件夹后系统自动用 LLM 分析
每一份文件（PDF/Word/Excel/图片），提取关键字段，导出 CSV。网址：{SITE_URL}

请自然地把高优先级关键词融入 title 和 description（不要生硬堆砌关键词），
只返回下面字段的 JSON，不要输出其他文字：
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
- 英文
- 不要提及网站上没有出现过的功能
"""
    response = client.chat.completions.create(
        model=LM_MODEL_NAME,
        messages=[
            {"role": "system", "content": "You are a professional SEO copywriter. Only output valid JSON."},
            {"role": "user", "content": prompt},
        ],
        temperature=0.4,
    )
    content = response.choices[0].message.content.strip()
    content = re.sub(r"^```json\s*|\s*```$", "", content, flags=re.MULTILINE).strip()
    return json.loads(content)


# ------------------------------------------------------------------
# 5. AI 自动结构化数据 —— 从页面 FAQ 区块自动生成 FAQPage schema
# ------------------------------------------------------------------
def extract_faq_pairs(html: str):
    """从 FAQ 区块（Frequently Asked Questions 标题下的 .step-item）提取问答对"""
    faq_section_match = re.search(
        r"Frequently Asked Questions.*?<div class=\"steps-container\">(.*?)</div>\s*</div>",
        html, re.DOTALL | re.IGNORECASE,
    )
    if not faq_section_match:
        return []
    section = faq_section_match.group(1)
    pairs = re.findall(r"<h4>(.*?)</h4>\s*<p>(.*?)</p>", section, re.DOTALL | re.IGNORECASE)
    return [(re.sub(r"<[^>]+>", "", q).strip(), re.sub(r"<[^>]+>", "", a).strip()) for q, a in pairs]


def build_faq_schema(faq_pairs) -> str:
    if not faq_pairs:
        return ""
    entities = [
        {
            "@type": "Question",
            "name": q,
            "acceptedAnswer": {"@type": "Answer", "text": a},
        }
        for q, a in faq_pairs
    ]
    schema = {"@context": "https://schema.org", "@type": "FAQPage", "mainEntity": entities}
    return f'<script type="application/ld+json">\n{json.dumps(schema, ensure_ascii=False, indent=2)}\n</script>'


# ------------------------------------------------------------------
# 把 meta 建议 + FAQ schema 一起写回 <head>，绝不碰 body/style/script
# ------------------------------------------------------------------
def apply_seo_head(html: str, seo: dict, faq_schema: str) -> str:
    head_match = re.search(r"(<head>)(.*?)(</head>)", html, re.DOTALL | re.IGNORECASE)
    if not head_match:
        raise ValueError("找不到 <head> 区域")

    head_content = head_match.group(2)

    if re.search(r"<title>.*?</title>", head_content, re.IGNORECASE | re.DOTALL):
        head_content = re.sub(
            r"<title>.*?</title>", f"<title>{seo['title']}</title>",
            head_content, flags=re.IGNORECASE | re.DOTALL,
        )
    else:
        head_content = f"<title>{seo['title']}</title>\n" + head_content

    # 清掉之前脚本留下的旧 SEO 标签，避免越堆越多
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
    {faq_schema}
"""

    new_head_content = head_content.rstrip() + "\n" + seo_block
    new_html = html[: head_match.start(2)] + new_head_content + html[head_match.end(2):]
    return new_html


# ------------------------------------------------------------------
# 4. AI 自动 SEO 审计（技术性检查清单，每天跑）
# ------------------------------------------------------------------
def run_seo_audit(html: str) -> list:
    findings = []
    head = read_head_section(html)

    title_match = re.search(r"<title>(.*?)</title>", head, re.IGNORECASE | re.DOTALL)
    title = title_match.group(1) if title_match else ""
    if not (10 <= len(title) <= 60):
        findings.append(f"⚠️ Title 长度为 {len(title)} 字符，建议控制在 60 字符以内")

    desc_match = re.search(r'<meta name="description" content="(.*?)"', head, re.IGNORECASE)
    desc = desc_match.group(1) if desc_match else ""
    if not (120 <= len(desc) <= 160):
        findings.append(f"⚠️ Description 长度为 {len(desc)} 字符，理想区间 120-160")

    if 'rel="canonical"' not in head:
        findings.append("❌ 缺少 canonical 标签")

    if "<h1" not in html:
        findings.append("ℹ️ 页面没有 <h1> 标签（目前用 h2 当主标题，出于不改版面考虑暂不自动修改，建议人工评估是否要调整）")

    try:
        r = requests.get(SITE_URL + "sitemap.xml", timeout=10)
        if r.status_code != 200:
            findings.append(f"❌ sitemap.xml 无法访问，状态码 {r.status_code}")
    except Exception as e:
        findings.append(f"❌ sitemap.xml 请求失败：{e}")

    try:
        r = requests.get(SITE_URL + "robots.txt", timeout=10)
        if r.status_code == 200 and "Disallow: /" in r.text:
            findings.append("❌ robots.txt 里有 Disallow: /，可能封锁了整个网站被收录")
    except Exception:
        pass  # 404 是正常情况，代表没有限制

    return findings


# ------------------------------------------------------------------
# 6. 内容差距分析（对比竞品，只生成建议清单，不自动改动网站，每周一跑）
# ------------------------------------------------------------------
def fetch_competitor_text(url: str) -> str:
    try:
        r = requests.get(url, timeout=15, headers={"User-Agent": "Mozilla/5.0"})
        soup = BeautifulSoup(r.text, "html.parser")
        for tag in soup(["script", "style"]):
            tag.decompose()
        text = soup.get_text(separator=" ")
        text = re.sub(r"\s+", " ", text).strip()
        return text[:2000]
    except Exception as e:
        log(f"⚠️ 抓取竞品失败 {url}: {e}")
        return ""


def run_content_gap_analysis(own_text: str):
    competitor_texts = []
    for url in COMPETITOR_URLS:
        text = fetch_competitor_text(url)
        if text:
            competitor_texts.append(f"[{url}]\n{text}")

    if not competitor_texts:
        log("⚠️ 内容差距分析：未能抓取到任何竞品内容，本次跳过")
        return

    prompt = f"""
你是内容策略分析师。下面是我们网站现有的文字内容：

{own_text}

下面是几个同类竞品网站的内容：

{chr(10).join(competitor_texts)}

请找出竞品提到、但我们网站完全没有覆盖的主题/关键词/使用场景，列出最多 5 条具体的
"建议补充内容"清单，每条一两句话说明可以怎么补充。只输出清单文字，不要输出 JSON。
"""
    response = client.chat.completions.create(
        model=LM_MODEL_NAME,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.5,
    )
    suggestions = response.choices[0].message.content.strip()
    log(f"📋 本周内容差距分析建议（仅供参考，需人工确认后再手动采纳，不会自动改动网站）：\n{suggestions}")


# ------------------------------------------------------------------
# Git 自动提交 + 推送到 GitHub
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
# 主流程
# ------------------------------------------------------------------
def main():
    log("===== SEO Agent 开始运行 =====")
    try:
        with open(INDEX_HTML_PATH, "r", encoding="utf-8") as f:
            html = f.read()

        backup_path = INDEX_HTML_PATH + f".backup-{datetime.date.today().isoformat()}"
        with open(backup_path, "w", encoding="utf-8") as f:
            f.write(html)
        log(f"已备份原文件到 {backup_path}")

        body_text = read_body_text(html)

        # 1+2. 关键词研究与分析
        keyword_strategy = generate_keyword_strategy(body_text)
        log(f"🔑 关键词策略：\n{json.dumps(keyword_strategy, ensure_ascii=False, indent=2)}")

        # 3. 内容优化（meta 建议，接入关键词）
        current_head = read_head_section(html)
        seo = generate_seo_suggestions(current_head, keyword_strategy)
        log(f"✏️ SEO meta 建议：\n{json.dumps(seo, ensure_ascii=False, indent=2)}")

        # 5. 结构化数据（FAQ schema）
        faq_pairs = extract_faq_pairs(html)
        faq_schema = build_faq_schema(faq_pairs)
        log(f"🏷️ 提取到 {len(faq_pairs)} 条 FAQ，已生成 FAQPage 结构化数据")

        new_html = apply_seo_head(html, seo, faq_schema)
        with open(INDEX_HTML_PATH, "w", encoding="utf-8") as f:
            f.write(new_html)
        log("已写回 index.html（只有 <head> 区域有变化，版面/样式/脚本完全未动）")

        # 4. SEO 审计
        audit_findings = run_seo_audit(new_html)
        if audit_findings:
            log("🔍 SEO 审计发现：\n" + "\n".join(audit_findings))
        else:
            log("🔍 SEO 审计：一切正常")

        # 6. 每周一跑内容差距分析
        if datetime.date.today().weekday() == 0:
            log("📅 今天是星期一，执行每周内容差距分析...")
            run_content_gap_analysis(body_text)

        git_commit_and_push()

        log("===== SEO Agent 运行完成（已 push 到 GitHub，等待 cPanel Cron Job 拉取）=====")
    except Exception as e:
        log(f"❌ 运行出错: {e}")
        raise


if __name__ == "__main__":
    main()