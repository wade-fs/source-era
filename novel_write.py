#!/usr/bin/env python3
"""
novel_write.py - {NOVEL_TITLE} 寫作助手
使用 Gemini Context Caching API 快取世界觀聖經，大幅節省 token

原理：
  Context Caching = 把「聖經文件」在 Google 伺服器端預先處理並快取。
  後續每次呼叫只需傳「快取 ID + 本次任務」，聖經部分的 token 費用減少 75%。
  快取最短存活 5 分鐘，可設定到數小時，適合密集寫作 session。

用法:
  # 首次使用：建立聖經快取
  ./novel_write.py cache-create

  # 查看現有快取
  ./novel_write.py cache-list

  # 寫新章節（帶入前後章節確保連貫）
  ./novel_write.py write --chapter 066 --prev 3

  # 批次寫新章節
  ./novel_write.py batch --start 67 --end 70

  # 擴寫現有章節
  ./novel_write.py expand --chapter 041

  # 刪除快取
  ./novel_write.py cache-delete
"""

"""
   - models/gemini-2.5-flash (Stable version of Gemini 2.5 Flash, our mid-size multimodal model that supports up to 1 million tokens, released in June of 2025.)
   - models/gemini-2.5-pro (Stable release (June 17th, 2025) of Gemini 2.5 Pro)
   - models/gemini-2.0-flash (Gemini 2.0 Flash)
   - models/gemini-2.0-flash-001 (Stable version of Gemini 2.0 Flash, our fast and versatile multimodal model for scaling across diverse tasks, released in January of 2025.)
   - models/gemini-2.0-flash-lite-001 (Stable version of Gemini 2.0 Flash-Lite)
   - models/gemini-2.0-flash-lite (Gemini 2.0 Flash-Lite)
   - models/gemini-2.5-flash-preview-tts (Gemini 2.5 Flash Preview TTS)
   - models/gemini-2.5-pro-preview-tts (Gemini 2.5 Pro Preview TTS)
   - models/gemini-flash-latest (Latest release of Gemini Flash)
   - models/gemini-flash-lite-latest (Latest release of Gemini Flash-Lite)
   - models/gemini-pro-latest (Latest release of Gemini Pro)
   - models/gemini-2.5-flash-lite (Stable version of Gemini 2.5 Flash-Lite, released in July of 2025)
   - models/gemini-2.5-flash-image (Gemini 2.5 Flash Preview Image)
   - models/gemini-3-pro-preview (Gemini 3 Pro Preview)
   - models/gemini-3-flash-preview (Gemini 3 Flash Preview)
   - models/gemini-3.1-pro-preview (Gemini 3.1 Pro Preview)
   - models/gemini-3.1-pro-preview-customtools (Gemini 3.1 Pro Preview optimized for custom tool usage)
   - models/gemini-3.1-flash-lite-preview (Gemini 3.1 Flash Lite Preview)
   - models/gemini-3.1-flash-lite (Gemini 3.1 Flash Lite)
   - models/gemini-3-pro-image-preview (Gemini 3 Pro Image Preview)
   - models/gemini-3-pro-image (Gemini 3 Pro Image)
   - models/gemini-3.1-flash-image-preview (Gemini 3.1 Flash Image Preview.)
   - models/gemini-3.1-flash-image (Gemini 3.1 Flash Image.)
   - models/gemini-3.5-flash (Gemini 3.5 Flash)
   - models/gemini-3.1-flash-tts-preview (Gemini 3.1 Flash TTS Preview)
   - models/gemini-robotics-er-1.5-preview (Gemini Robotics-ER 1.5 Preview)
   - models/gemini-robotics-er-1.6-preview (Gemini Robotics-ER 1.6 Preview)
   - models/gemini-2.5-computer-use-preview-10-2025 (Gemini 2.5 Computer Use Preview 10-2025)
   - models/gemini-embedding-001 (Obtain a distributed representation of a text.)
   - models/gemini-embedding-2-preview (Obtain a distributed representation of multimodal content.)
   - models/gemini-embedding-2 (Obtain a distributed representation of multimodal content.
"""

import os
import sys
import json
import argparse
import requests

import re
import time
from pathlib import Path

# ─── 設定 ────────────────────────────────────────────────────────────────────
API_KEY  = os.environ.get("GEMINI_API_KEY", "")
BASE_URL = "https://generativelanguage.googleapis.com"
# MODEL    = "models/gemini-3.5-flash"   # 你的 API 確認存在的最新版本
MODEL    = "models/gemini-flash-lite-latest"   # 你的 API 確認存在的最新版本

PROJECT_ROOT = Path(__file__).parent
CACHE_FILE   = PROJECT_ROOT / ".cache_id.json"   # 儲存 cachedContent name


def parse_manifest_metadata() -> dict:
    """從 docs/manifest.md 的 Metadata 區塊讀取小說基本資訊"""
    manifest_path = PROJECT_ROOT / "docs" / "manifest.md"
    meta = {
        "title": "未命名小說",
        "cache_display_name": "小說聖經",
        "style": "",
    }
    if not manifest_path.exists():
        return meta
    import re
    text = manifest_path.read_text(encoding="utf-8")
    in_meta = False
    for line in text.splitlines():
        if line.strip() == "## Metadata":
            in_meta = True
            continue
        if in_meta and line.startswith("##"):
            break
        if in_meta and line.strip().startswith("- "):
            m = re.match(r"-\s+(\w+):\s*(.+)", line.strip())
            if m:
                meta[m.group(1)] = m.group(2).strip()
    return meta

NOVEL_META = parse_manifest_metadata()
NOVEL_TITLE = NOVEL_META["title"]
NOVEL_CACHE_NAME = NOVEL_META["cache_display_name"]
NOVEL_STYLE = NOVEL_META["style"]

def load_bible_files() -> list:
    """從 docs/manifest.md 讀取 Priority 0 和 Priority 1 的檔案清單"""
    import re
    manifest_path = PROJECT_ROOT / "docs" / "manifest.md"
    if not manifest_path.exists():
        print("⚠️  找不到 docs/manifest.md，改用 canon/ + rules/ 全部檔案")
        defaults = []
        for pattern in ["docs/canon/*.md", "docs/rules/*.md"]:
            defaults.extend(sorted(PROJECT_ROOT.glob(pattern)))
        return defaults

    text = manifest_path.read_text(encoding="utf-8")
    files = []
    in_p0_or_p1 = False
    for line in text.splitlines():
        if re.match(r"###\s+Priority [01]", line):
            in_p0_or_p1 = True
        elif re.match(r"###\s+Priority [2-9]", line):
            in_p0_or_p1 = False
        elif in_p0_or_p1 and line.strip().startswith("- docs/"):
            raw = line.strip().lstrip("- ")
            if "*" in raw:
                files.extend(sorted(PROJECT_ROOT.glob(raw)))
            else:
                p = PROJECT_ROOT / raw
                if p.exists():
                    files.append(p)
    return files

# 要進入快取的「聖經」文件（從 docs/manifest.md Priority 0+1 讀取）
BIBLE_FILES = load_bible_files()

# 快取 TTL（秒）。寫作 session 建議 3600（1 小時），長期存放最多 86400
CACHE_TTL_SECONDS = 86400

USAGE_FILE = PROJECT_ROOT / ".usage.json"


# ─── 輔助 ─────────────────────────────────────────────────────────────────────

def log_usage(input_tok, output_tok):
    """記錄消耗到本地"""
    data = {}
    if USAGE_FILE.exists():
        data = json.loads(USAGE_FILE.read_text())
    
    data["input"] = data.get("input", 0) + input_tok
    data["output"] = data.get("output", 0) + output_tok
    USAGE_FILE.write_text(json.dumps(data))

def cmd_usage(args):
    """查詢本機累積紀錄"""
    if not USAGE_FILE.exists():
        print("尚無使用紀錄")
        return
    data = json.loads(USAGE_FILE.read_text())
    print(f"📈 本地累計消耗:")
    print(f"   輸入 Token: {data['input']:,}")
    print(f"   輸出 Token: {data['output']:,}")
    print(f"   https://aistudio.google.com/billing")

def cmd_list_models(args):
    """列出可用模型"""
    check_api_key()
    url = f"{BASE_URL}/v1beta/models?key={API_KEY}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"❌ 無法獲取模型列表: {resp.text}")
        return

    models = resp.json().get("models", [])
    print(f"🤖 可用模型清單:")
    for m in models:
        # 只顯示包含 gemini 的模型
        if "gemini" in m['name']:
            print(f"   - {m['name']} ({m.get('description', '無描述')})")

def get_path_info(chapter_num: int):
    # 改為每 80 章一卷
    volume = (chapter_num - 1) // 80 + 1
    volume_str = f"{volume:02d}"
    
    chapter_dir = PROJECT_ROOT / "chapter" / volume_str
    chapter_dir.mkdir(parents=True, exist_ok=True)
    
    # 指向新的目錄結構
    outline_path = PROJECT_ROOT / "docs" / "volumes" / f"vol{volume_str}" / "chapter_outline.md"
    
    return {
        "volume": volume,
        "volume_str": volume_str,
        "chapter_dir": chapter_dir,
        "outline_path": outline_path,
        "outline_glob": "chapter_outline.md" # 改為精確檔名
    }

def get_volume_act_info(chapter_num: int) -> tuple[str, str]:
    """
    動態從 docs/volumes/vol{XX}/chapter_outline.md 取得卷名與階段名。
    自動計算每 80 章為一卷。
    """
    # 根據您的定義，每 80 章為一卷 (1-80 卷一, 81-160 卷二)
    volume = (chapter_num - 1) // 80 + 1
    volume_str = f"{volume:02d}"
    
    # 定位到正確的綱要路徑
    outline_path = PROJECT_ROOT / "docs" / "volumes" / f"vol{volume_str}" / "chapter_outline.md"
    
    # 預設值 (防呆)
    volume_title = f"第 {volume} 卷"
    act_title = "當前階段"
    
    if outline_path.exists():
        text = outline_path.read_text(encoding="utf-8")
        
        # 1. 解析卷名 (尋找第一個單獨的 # 開頭標題)
        # 匹配: "# 卷二：雅典之問 —— 理性誕生"
        m_vol = re.search(r"^#\s+(.+)", text, re.M)
        if m_vol:
            volume_title = m_vol.group(1).strip()
            
        # 2. 解析階段名 (尋找 ### 開頭並帶有章節範圍的標題)
        # 匹配: "### 第一階段：理性的晨曦 (Ch081 - Ch095)"
        for line in text.splitlines():
            if line.startswith("### "):
                # 抓取範圍，例如 Ch081 - Ch095
                m_act = re.search(r"Ch(\d+)\s*-\s*Ch?(\d+)", line, re.IGNORECASE)
                if m_act:
                    start_ch = int(m_act.group(1))
                    end_ch = int(m_act.group(2))
                    if start_ch <= chapter_num <= end_ch:
                        # 移除前面的 "### "
                        raw_title = line.lstrip("# ").strip()
                        # 移除後面的 "(Ch081 - Ch095)" 保留乾淨的階段名稱
                        act_title = re.sub(r"\s*\(Ch\d+\s*-\s*Ch?\d+\)\s*", "", raw_title, flags=re.IGNORECASE).strip()
                        break
                        
    return volume_title, act_title

def parse_outline(outline_path: Path) -> dict[int, str]:
    text = outline_path.read_text(encoding="utf-8")
    result = {}
    
    # 針對您綱要格式：81. **Ch081 奧林匹斯的退潮**：維知重返愛琴海...
    # 我們調整 Regex 來抓取數字、標題與說明
    pattern = re.compile(
        r'(\d+)\.\s+\*\*Ch\d+\s+(.*?)\*\*：(.*?)(?=\n\d+\.|\Z)',
        re.DOTALL
    )

    for m in pattern.finditer(text):
        ch_num = int(m.group(1))
        title  = m.group(2).strip()
        body   = m.group(3).strip()
        result[ch_num] = f"【{title}】\n{body}"

    return result


def get_nav_links(chapter_num: int) -> str:
    links = []
    
    if chapter_num > 1:
        prev_num = chapter_num - 1
        prev_vol = (prev_num - 1) // 80 + 1
        links.append(f"[上一章：第 {prev_num} 章](../{prev_vol:02d}/ch{prev_num:04d}.md)")
        
    links.append("[回目錄](../../README.md)")
    
    next_num = chapter_num + 1
    next_vol = (next_num - 1) // 80 + 1
    links.append(f"[下一章：第 {next_num} 章](../{next_vol:02d}/ch{next_num:04d}.md)")

    return " | ".join(links)

def cmd_batch(args):
    # ... 前置碼
    # 使用 get_path_info 取得該起始章節對應的綱要
    path_info = get_path_info(args.start)
    outline_path = path_info["outline_path"]

    # 找綱要檔
    if not outline_path.exists():
        candidates = list((PROJECT_ROOT / "docs").glob(path_info["outline_glob"]))
        if candidates:
            outline_path = candidates[0]
            print(f"   自動找到綱要: {outline_path.name}")
        else:
            all_files = [f.name for f in (PROJECT_ROOT / "docs").iterdir() if "綱要" in f.name]
            print(f"❌ 找不到綱要檔: {outline_path.name}")
            print(f"   目前資料夾內的綱要檔: {all_files}")
            sys.exit(1)

    # 解析綱要
    outline = parse_outline(outline_path)
    if not outline:
        print("❌ 無法從綱要檔解析出任何章節")
        sys.exit(1)

    # 決定要寫哪些章節
    start = args.start
    end   = args.end if args.end else max(outline.keys())
    targets = [n for n in range(start, end + 1) if n in outline]

    if not targets:
        print(f"❌ 綱要中找不到第 {start}～{end} 章")
        print(f"   綱要涵蓋範圍: 第 {min(outline)} ～ 第 {max(outline)} 章")
        sys.exit(1)

    # 過濾已存在的章節
    skip = []
    todo = []
    for n in targets:
        ch_path_info = get_path_info(n)
        ch_path = ch_path_info["chapter_dir"] / f"ch{n:04d}.md"
        if ch_path.exists() and not args.overwrite:
            skip.append(n)
        else:
            todo.append(n)

    print(f"\n📋 批次寫作計畫")
    print(f"   綱要: {outline_path.name}")
    print(f"   範圍: 第 {start} ～ {end} 章（共 {len(targets)} 章）")
    if skip:
        print(f"   跳過: {skip}（已存在，用 --overwrite 強制覆蓋）")
    print(f"   待寫: {len(todo)} 章")
    print(f"   前文: 每章帶入前 {args.prev} 章作為連貫 context")
    print(f"   間隔: 每章之間暫停 {args.delay} 秒（避免 rate limit）\n")

    if not todo:
        print("✅ 所有章節已存在，無需寫作")
        return

    # 逐章生成
    success = []
    failed  = []

    for idx, ch_num in enumerate(todo, 1):
        prompt = outline[ch_num]
        ch_path_info = get_path_info(ch_num)
        ch_path = ch_path_info["chapter_dir"] / f"ch{ch_num:04d}.md"

        print(f"[{idx}/{len(todo)}] 第 {ch_num} 章：{prompt[:40]}...")

        # 讀取前 N 章
        prev_chapters = []
        for i in range(max(1, ch_num - args.prev), ch_num):
            p_info = get_path_info(i)
            p = p_info["chapter_dir"] / f"ch{i:04d}.md"
            if p.exists():
                prev_chapters.append((i, p.read_text(encoding="utf-8")))

        extra_parts = []
        if prev_chapters:
            prev_text = "\n\n---\n\n".join(
                f"【第 {n} 章 原文】\n{content}" for n, content in prev_chapters
            )
            extra_parts.append({"text": f"緊接在新章節之前的章節，請確保情節完全銜接：\n\n{prev_text}"})

        # === 動態標題（無論有無前文都要加）===
        volume_title, act_title = get_volume_act_info(ch_num)
        chapter_title = prompt.split('】')[0].replace('【', '').strip() if '【' in prompt else "章節標題"
        nav_links = get_nav_links(ch_num)

        novel_title = NOVEL_TITLE
        extra_parts.append({"text": f"""
請撰寫《{novel_title}》第 {ch_num} 章的完整正文。

=== 必須嚴格遵守的輸出結構 ===

# {novel_title}

## {volume_title}

### {act_title}

第 {ch_num} 章：{chapter_title}

{nav_links}

---

（以下開始正文內容）

{nav_links}

章節情節提示：
{prompt}

=== 寫作要求 ===
- 必須完整輸出上方標題結構（包含 #、##、###、第X章 與 導覽連結）。
- 字數至少 3500 字。
- Markdown 格式。
- 直接輸出，不要額外說明。
"""})

        gen_config = {"temperature": 0.85, "maxOutputTokens": 8192}

        MIN_CHARS = 3500
        try:
            data, text = generate_with_retry(extra_parts, gen_config, min_chars=MIN_CHARS)

            ch_path.write_text(text, encoding="utf-8")
            zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')

            usage = data.get("usageMetadata", {})
            cached_tok = usage.get("cachedContentTokenCount", 0)
            in_tok  = usage.get("promptTokenCount", 0)
            out_tok = usage.get("candidatesTokenCount", 0)
            print(f"   ✅ 完成 {zh_count:,} 字  |  輸出 {out_tok} tok  |  快取命中 {cached_tok} tok")
            log_usage(in_tok, out_tok)

            success.append(ch_num)

        except SystemExit:
            print(f"   ❌ 第 {ch_num} 章生成失敗，繼續下一章...")
            failed.append(ch_num)

        # 章節間暫停，避免 rate limit
        if idx < len(todo):
            time.sleep(args.delay)

    # 結果摘要
    print(f"\n{'='*50}")
    print(f"批次完成：成功 {len(success)} 章，失敗 {len(failed)} 章")
    if success:
        print(f"  ✅ 已完成: {success}")
    if failed:
        print(f"  ❌ 失敗:   {failed}")
        print(f"     可單獨重跑: python novel_write.py write --chapter N")

def check_api_key():
    if not API_KEY:
        print("❌ 找不到 GEMINI_API_KEY 環境變數")
        print("   請先執行: export GEMINI_API_KEY='AIza...'")
        print("   或: source .env")
        sys.exit(1)


def load_cache_id() -> str | None:
    if CACHE_FILE.exists():
        data = json.loads(CACHE_FILE.read_text())
        return data.get("name")
    return None


def save_cache_id(name: str):
    CACHE_FILE.write_text(json.dumps({"name": name}, ensure_ascii=False, indent=2))


def call_gemini(payload: dict) -> dict:
    url = f"{BASE_URL}/v1beta/{MODEL}:generateContent?key={API_KEY}"
    resp = requests.post(url, json=payload, timeout=120)
    if resp.status_code != 200:
        print(f"❌ API 錯誤 ({resp.status_code}):")
        print(resp.text[:800])
        sys.exit(1)
    return resp.json()


def extract_text(data: dict) -> str:
    text = ""
    try:
        for part in data["candidates"][0]["content"]["parts"]:
            text += part.get("text", "")
    except (KeyError, IndexError):
        print("❌ 無法解析回應：", json.dumps(data, ensure_ascii=False)[:500])
        sys.exit(1)
    return text


def count_zh(text: str) -> int:
    """計算純中文字數"""
    return sum(1 for c in text if '\u4e00' <= c <= '\u9fff')


def generate_with_retry(
    extra_parts: list,
    gen_config: dict,
    min_chars: int = 3500,
    max_retries: int = 2,
) -> tuple[dict, str]:
    """
    呼叫 Gemini 生成，若字數不足 min_chars 則補一句提醒再重試一次。
    字數規範已寫入 README.md 快取，不需在 prompt 中重複長篇說明。
    回傳 (data, text)。
    """
    cache_name = load_cache_id()
    zh = 0

    for attempt in range(1, max_retries + 1):
        parts = list(extra_parts)
        if attempt > 1:
            parts.append({"text": f"字數仍不足 {min_chars} 字，請繼續補充細節直到達標。"})

        if cache_name:
            payload = build_payload_with_cache(cache_name, parts, gen_config)
        else:
            readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
            payload = build_payload_no_cache(readme, parts, gen_config)

        data = call_gemini(payload)
        text = extract_text(data)
        zh = count_zh(text)

        if zh >= min_chars:
            return data, text

        print(f"   ⚠️ 第 {attempt} 次生成僅 {zh:,} 字（要求 {min_chars:,} 字），重試...")

    print(f"   ⚠️ 達到最大重試次數，以最後結果（{zh:,} 字）儲存")
    return data, text


def print_usage(data: dict):
    if "usageMetadata" in data:
        u = data["usageMetadata"]
        cached    = u.get("cachedContentTokenCount", 0)
        total_in  = u.get("promptTokenCount", 0)
        total_out = u.get("candidatesTokenCount", 0)
        print(f"\n📊 Token 用量:")
        print(f"   輸入總計: {total_in}（其中快取命中: {cached}，節省 75% 費用）")
        print(f"   輸出:     {total_out}")
        log_usage(total_in, total_out)


# ─── Context Caching ──────────────────────────────────────────────────────────
def cmd_cache_create(args):
    """
    把所有聖經文件合併成一個大文字，上傳建立 cachedContent。
    之後每次呼叫帶入 cache name，Gemini 直接從快取讀取，不重新計算。
    """
    check_api_key()

    # 合併所有聖經文件
    parts_text = []
    for path in BIBLE_FILES:
        if not path.exists():
            print(f"  ⚠️  找不到: {path}，跳過")
            continue
        content = path.read_text(encoding="utf-8")
        parts_text.append(f"# [{path.name}]\n\n{content}")
        print(f"  ✅ 已讀取: {path.name}（{len(content):,} bytes）")

    combined = "\n\n---\n\n".join(parts_text)
    char_count = len(combined)
    print(f"\n📦 聖經合計: {char_count:,} 字元，準備建立快取...")

    # 建立 cachedContent
    novel_title = NOVEL_TITLE
    url = f"{BASE_URL}/v1beta/cachedContents?key={API_KEY}"
    payload = {
        "model": MODEL,
        "displayName": f"{novel_title}聖經",
        "contents": [
            {
                "role": "user",
                "parts": [{"text": combined}]
            }
        ],
        "ttl": f"{CACHE_TTL_SECONDS}s",
        "systemInstruction": {
            "parts": [{
                "text": (
                    f"你是《{novel_title}》的專屬寫作助手。"
                    "以上是本作的完整世界觀聖經、符紋體系、人物設定與章節規劃。"
                    "撰寫時必須嚴格遵守這些設定，保持前後連貫。"
                    f"風格要求：{NOVEL_STYLE}"
                )
            }]
        }
    }

    resp = requests.post(url, json=payload, timeout=60)
    if resp.status_code != 200:
        print(f"❌ 建立快取失敗 ({resp.status_code}):")
        print(resp.text[:800])
        sys.exit(1)

    data = resp.json()
    name = data.get("name")
    expire = data.get("expireTime", "未知")[:19].replace("T", " ")

    save_cache_id(name)
    print(f"\n✅ 快取建立成功！")
    print(f"   ID:     {name}")
    print(f"   到期:   {expire} UTC（{CACHE_TTL_SECONDS // 60} 分鐘後）")
    print(f"   存檔:   {CACHE_FILE}")
    print(f"\n   之後寫作只需呼叫此快取，聖經 token 費用減少 75%。")
    print(f"   快取過期後重新執行 cache-create 即可。")


def cmd_cache_list(args):
    """列出所有 cachedContents"""
    check_api_key()
    url = f"{BASE_URL}/v1beta/cachedContents?key={API_KEY}"
    resp = requests.get(url, timeout=30)
    if resp.status_code != 200:
        print(f"❌ ({resp.status_code}): {resp.text[:300]}")
        sys.exit(1)

    items = resp.json().get("cachedContents", [])
    local_name = load_cache_id()

    if not items:
        print("目前沒有任何 cachedContent")
        return

    print(f"☁️  現有快取（共 {len(items)} 個）:")
    for item in items:
        name = item.get("name", "")
        display = item.get("displayName", "")
        expire = item.get("expireTime", "")[:19].replace("T", " ")
        tokens = item.get("usageMetadata", {}).get("totalTokenCount", "?")
        flag = " ← 本地使用中" if name == local_name else ""
        print(f"   {name}")
        print(f"      名稱: {display}  token: {tokens}  到期: {expire} UTC{flag}")


def cmd_cache_delete(args):
    """刪除快取"""
    check_api_key()
    name = load_cache_id()
    if not name:
        print("找不到本地快取記錄")
        return

    url = f"{BASE_URL}/v1beta/{name}?key={API_KEY}"
    resp = requests.delete(url, timeout=30)
    if resp.status_code in (200, 204):
        CACHE_FILE.unlink(missing_ok=True)
        print(f"✅ 已刪除快取: {name}")
    else:
        print(f"❌ 刪除失敗 ({resp.status_code}): {resp.text[:300]}")


# ─── 寫作指令 ──────────────────────────────────────────────────────────────────
def build_payload_with_cache(cache_name: str, extra_parts: list, gen_config: dict) -> dict:
    """組裝帶有快取引用的 API payload"""
    return {
        "cachedContent": cache_name,
        "contents": [
            {
                "role": "user",
                "parts": extra_parts
            }
        ],
        "generationConfig": gen_config,
    }


def build_payload_no_cache(bible_inline: str, extra_parts: list, gen_config: dict) -> dict:
    """快取過期時的 fallback：把聖經文字直接內嵌"""
    return {
        "contents": [
            {
                "role": "user",
                "parts": [{"text": f"【世界觀聖經】\n{bible_inline}\n\n---\n"}] + extra_parts
            }
        ],
        "generationConfig": gen_config,
    }


def get_payload(extra_parts: list, gen_config: dict) -> dict:
    """嘗試使用快取，失敗則 fallback 到內嵌模式"""
    cache_name = load_cache_id()
    if cache_name:
        print(f"   使用快取: {cache_name}")
        return build_payload_with_cache(cache_name, extra_parts, gen_config)
    else:
        print("   ⚠️  無快取，改用內嵌模式（token 較多）")
        print("      建議先執行: python novel_write.py cache-create")
        # fallback：讀 README 作為最小聖經
        readme = (PROJECT_ROOT / "README.md").read_text(encoding="utf-8")
        return build_payload_no_cache(readme, extra_parts, gen_config)

def get_chapter_title(chapter_prompt: str) -> str | None:
    m = re.match(r"\s*【(.+?)】", chapter_prompt)

    if m:
        return m.group(1).strip()

    return None


def cmd_write(args):
    check_api_key()
    chapter_num = int(args.chapter)
    
    # --- 修正處：直接從 path_info 取得正確綱要 ---
    path_info = get_path_info(chapter_num)
    outline_path = path_info["outline_path"] 
    
    chapter_prompt = args.prompt

    if outline_path.exists():
        try:
            outline = parse_outline(outline_path)
            # 注意：如果 outline 裡的 key 是整數（例如 81），這裡就能正確對應
            if chapter_num in outline:
                chapter_prompt = outline[chapter_num]
        except Exception as e:
            print(f"   ⚠️ 綱要讀取失敗: {e}")

    title = get_chapter_title(chapter_prompt)
    if not title:
        title = f"第{chapter_num}章"

    # 讀取前 N 章作為連貫 context
    prev_count = args.prev
    prev_chapters = []
    for i in range(max(1, chapter_num - prev_count), chapter_num):
        p_info = get_path_info(i)
        ch_path = p_info["chapter_dir"] / f"ch{i:04d}.md"
        if ch_path.exists():
            prev_chapters.append((i, ch_path.read_text(encoding="utf-8")))

    extra_parts = []
    if prev_chapters:
        prev_text = "\n\n---\n\n".join(
            f"【第 {n} 章 原文】\n{content}" for n, content in prev_chapters
        )
        extra_parts.append({
            "text": f"以下是緊接在新章節之前的章節，請確保情節、人物狀態、時間線完全銜接：\n\n{prev_text}"
        })

        # 在 cmd_write 函數中
        volume_title, act_title = get_volume_act_info(chapter_num)
        novel_title = NOVEL_TITLE  # 直接使用全域變數
        nav_links = get_nav_links(chapter_num)

        # 修改輸出模板
        extra_parts.append({
            "text": f"""
# {novel_title}

## {volume_title}

### {act_title}

第 {chapter_num} 章：{title}

{nav_links}

---

（以下開始正文內容）

{nav_links}

---

本章劇情綱要：
{chapter_prompt}

=== 寫作要求 ===
1. 必須從上方完整標題結構開始輸出（包含導覽連結到 ---）。
2. 正文使用標準 Markdown 格式（段落、對話、**強調** 等）。
3. 字數至少 3500 字（純中文）。
4. 嚴格遵守世界觀聖經、人物設定與前文連貫性。
5. 風格：第三人稱有限視角、沉穩觀察、重視歷史細節與文明邏輯。
6. 禁止在正文前額外說明或 "已生成" 之類的文字。
"""
    })

    gen_config = {
        "temperature": 0.85,
        "maxOutputTokens": 8192,
    }

    MIN_CHARS = 3500
    print(f"\n🖊  生成第 {chapter_num} 章（引用前 {len(prev_chapters)} 章作為連貫 context，最少 {MIN_CHARS:,} 字）...")
    data, text = generate_with_retry(extra_parts, gen_config, min_chars=MIN_CHARS)

    # 輸出
    out_path = Path(args.output) if args.output else path_info["chapter_dir"] / f"ch{chapter_num:04d}.md"
    if args.dry_run:
        print(text)
    else:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        zh_count = sum(1 for c in text if '\u4e00' <= c <= '\u9fff')
        print(f"\n✅ 已儲存: {out_path}（約 {zh_count:,} 字）")

    print_usage(data)


def cmd_expand(args):
    """擴寫現有章節"""
    check_api_key()
    chapter_num = int(args.chapter)
    path_info = get_path_info(chapter_num)
    ch_path = path_info["chapter_dir"] / f"ch{chapter_num:04d}.md"

    if not ch_path.exists():
        print(f"❌ 找不到: {ch_path}")
        sys.exit(1)

    original = ch_path.read_text(encoding="utf-8")
    zh_count = count_zh(original)
    print(f"   原文: {zh_count:,} 字")
    volume_title, act_title = get_volume_act_info(chapter_num)
    nav_links = get_nav_links(chapter_num)

    # 嘗試抓取原有的章節標題，以利保留
    title = f"第 {chapter_num} 章"
    m = re.search(r"第\s*\d+\s*章[：\s]*(.*)", original)
    if m and m.group(1).strip():
        title = f"第 {chapter_num} 章：{m.group(1).strip()}"

    novel_title = NOVEL_TITLE
    extra_parts = [{
        "text": f"""
以下是《{novel_title}》第 {chapter_num} 章的草稿：

{original}

---
請在完整保留所有現有情節的前提下擴寫：
1. 補充場景的環境描寫和感官細節（氣味、溫度、光線、聲音）
2. 深化人物的內心活動和細微情緒變化
3. 讓對白更自然流暢，加入肢體語言與停頓
4. 目標字數：3500 字以上
5. 嚴格遵守世界觀設定，不添加任何違反設定的內容

=== 必須嚴格遵守的輸出結構 ===

# {novel_title}

## {volume_title}

### {act_title}

{title}

{nav_links}

---

（以下開始擴寫的正文內容）

---
{nav_links}

=== 寫作要求 ===
- 必須從上方完整標題結構開始輸出（包含導覽連結到 ---）。
- 請直接輸出完整擴寫版本，不需要說明或前言。
"""
    }]

    gen_config = {
        "temperature": 0.75,
        "maxOutputTokens": 16384,
    }

    print(f"\n✏️  擴寫第 {chapter_num} 章...")
    payload = get_payload(extra_parts, gen_config)
    data = call_gemini(payload)
    text = extract_text(data)

    # 備份原檔
    backup = ch_path.with_suffix(".md.bak")
    ch_path.rename(backup)
    ch_path.write_text(text, encoding="utf-8")

    new_count = count_zh(text)
    print(f"✅ 擴寫完成：{zh_count:,} → {new_count:,} 字")
    print(f"   原檔備份: {backup}")

    print_usage(data)


def cmd_synopsis(args):
    """根據指定章節範圍生成摘要（用於長篇連貫性維護）"""
    check_api_key()
    start, end = args.start, args.end

    chapters_text = []
    for i in range(start, end + 1):
        p_info = get_path_info(i)
        ch_path = p_info["chapter_dir"] / f"ch{i:04d}.md"
        if ch_path.exists():
            chapters_text.append(f"【第 {i} 章】\n{ch_path.read_text(encoding='utf-8')}")

    if not chapters_text:
        print("❌ 找不到任何章節")
        sys.exit(1)

    novel_title = NOVEL_TITLE
    extra_parts = [{
        "text": f"""
以下是《{novel_title}》第 {start}～{end} 章的內容：

{"".join(chapters_text)}

---
請生成這些章節的精簡摘要，包含：
1. 主要情節進展（按章節列出）
2. 人物狀態變化（林淵及其他重要角色）
3. 已揭露的重要世界觀資訊
4. 尚未解決的伏筆清單

格式：條列式，每章 2～3 句話即可。
"""
    }]

    print(f"\n📝 生成第 {start}～{end} 章摘要...")
    payload = get_payload(extra_parts, {"temperature": 0.3, "maxOutputTokens": 4096})
    data = call_gemini(payload)
    text = extract_text(data)

    out_path = PROJECT_ROOT / f"synopsis_ch{start:04d}-ch{end:04d}.md"
    out_path.write_text(text, encoding="utf-8")
    print(f"✅ 摘要已儲存: {out_path}")
    print_usage(data)


# ─── CLI ──────────────────────────────────────────────────────────────────────
def main():
    novel_title = NOVEL_TITLE
    parser = argparse.ArgumentParser(description=f"{novel_title} 寫作助手（Context Caching 版）")
    sub = parser.add_subparsers(dest="cmd", required=True)

    sub.add_parser("cache-create", help="建立/更新世界觀聖經快取（每次到期後需重新執行）")
    sub.add_parser("cache-list",   help="列出所有現有快取")
    sub.add_parser("cache-delete", help="刪除本地快取記錄")

    p_write = sub.add_parser("write", help="生成新章節")
    p_write.add_argument("--chapter", required=True, help="章節編號，例如 066")
    p_write.add_argument("--prev", type=int, default=3, help="帶入前幾章作為上下文（預設 3）")
    p_write.add_argument("--prompt", default="", help="本章情節提示")
    p_write.add_argument("--output", help="輸出路徑")
    p_write.add_argument("--dry-run", action="store_true", help="只印出結果，不存檔")

    p_expand = sub.add_parser("expand", help="擴寫現有章節")
    p_expand.add_argument("--chapter", required=True, help="章節編號")

    p_syn = sub.add_parser("synopsis", help="生成章節範圍摘要（維護長篇連貫性）")
    p_syn.add_argument("--start", type=int, required=True, help="起始章節")
    p_syn.add_argument("--end",   type=int, required=True, help="結束章節")

    p_batch = sub.add_parser("batch", help="從綱要 md 批次生成多個章節")
    p_batch.add_argument("--outline", default=None,
                         help="綱要檔路徑")
    p_batch.add_argument("--start",  type=int, required=True, help="起始章節號")
    p_batch.add_argument("--end",    type=int, default=None,  help="結束章節號")
    p_batch.add_argument("--prev",   type=int, default=3,     help="每章帶入前幾章作為上下文")
    p_batch.add_argument("--delay",  type=int, default=5,     help="每章之間的間隔秒數")
    p_batch.add_argument("--overwrite", action="store_true",  help="覆蓋已存在的章節")

    sub.add_parser("list-models", help="列出可用模型")
    sub.add_parser("usage",       help="查詢本地累計 Token 消耗")

    args = parser.parse_args()
    {
        "cache-create": cmd_cache_create,
        "cache-list":   cmd_cache_list,
        "cache-delete": cmd_cache_delete,
        "write":        cmd_write,
        "expand":       cmd_expand,
        "synopsis":     cmd_synopsis,
        "batch":        cmd_batch,
        "list-models":  cmd_list_models,
        "usage":        cmd_usage,
    }[args.cmd](args)


if __name__ == "__main__":
    main()

