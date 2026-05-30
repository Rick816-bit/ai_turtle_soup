"""海龟汤游戏核心逻辑：模型调用、要点提取、判答、题库加载。
CLI 和 Web 服务端都从这里调用，不含任何 IO 交互。
"""

import json
import os
import re
from pathlib import Path

from anthropic import Anthropic

MODEL = "deepseek-v4-pro"
BASE_URL = "https://api.deepseek.com/anthropic"
BASE_DIR = Path(__file__).parent
ENV_FILE = BASE_DIR / ".env"
PUZZLES_FILE = BASE_DIR / "puzzles.json"


def load_dotenv() -> None:
    """读取脚本同目录的 .env 注入环境变量（已有的不会覆盖）。"""
    if not ENV_FILE.exists():
        return
    for raw in ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


def save_to_dotenv(key: str, value: str) -> None:
    ENV_FILE.write_text(f"{key}={value}\n", encoding="utf-8")


_client: Anthropic | None = None


def get_client() -> Anthropic:
    """惰性创建 Anthropic 客户端，首次调用时校验 key。"""
    global _client
    if _client is None:
        load_dotenv()
        key = os.environ.get("DEEPSEEK_API_KEY", "").strip()
        if not key:
            raise RuntimeError(
                "未检测到 DEEPSEEK_API_KEY，请设置环境变量或写入 .env"
            )
        _client = Anthropic(api_key=key, base_url=BASE_URL)
    return _client


def _parse_json(text: str) -> dict:
    text = text.strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.DOTALL)
    if fence:
        text = fence.group(1)
    else:
        brace = re.search(r"\{.*\}", text, re.DOTALL)
        if brace:
            text = brace.group(0)
    return json.loads(text)


def _extract_text(resp) -> str:
    """跳过 ThinkingBlock，拼接所有 TextBlock 的内容。"""
    parts = []
    for block in resp.content:
        text = getattr(block, "text", None)
        if text:
            parts.append(text)
    return "\n".join(parts)


def _chat_json(prompt: str) -> dict:
    resp = get_client().messages.create(
        model=MODEL,
        max_tokens=2048,
        temperature=0.3,
        messages=[{"role": "user", "content": prompt}],
    )
    return _parse_json(_extract_text(resp))


def extract_key_points(soup_surface: str, soup_bottom: str) -> list[str]:
    prompt = f"""你是海龟汤出题人。请从下面的汤底中提取玩家需要猜出的关键要点。

【汤面】
{soup_surface}

【汤底】
{soup_bottom}

要求：
- 要点要覆盖汤底的核心真相（动机、手段、身份、关键转折等）
- 每条要点是一句简洁、可独立判断的陈述
- 一般 3~6 条，太多会让游戏拖沓

只返回 JSON：{{"key_points": ["要点1", "要点2", ...]}}"""
    return _chat_json(prompt)["key_points"]


def judge(
    soup_surface: str,
    soup_bottom: str,
    key_points: list[str],
    discovered: set[int],
    history: list[tuple[str, str]],
    question: str,
) -> dict:
    points_status = "\n".join(
        f"  [{i}] {'已揭示' if i in discovered else '未揭示'}：{p}"
        for i, p in enumerate(key_points)
    )
    history_str = (
        "\n".join(f"Q: {q}\nA: {a}" for q, a in history[-10:]) or "（暂无）"
    )

    prompt = f"""你是海龟汤主持人。你必须严格基于【汤底】判断玩家问题。

【汤面】（玩家已知）
{soup_surface}

【汤底】（真相，玩家不知道）
{soup_bottom}

【关键要点】
{points_status}

【最近问答】
{history_str}

【玩家新问题】
{question}

判断规则：
1. answer：根据汤底真相，回答以下之一：
   - "是"：问题描述与汤底相符
   - "不是"：问题描述与汤底矛盾
   - "是也不是"：部分相符、需要细分、或问题表述本身有歧义
   - "无关"：问题与汤底真相无关
2. newly_discovered：本轮问答**实质性**揭示了哪些**之前未揭示**的要点（返回索引数组）。
   - 必须是玩家通过这次问题真正问到了这个要点的核心，仅仅"擦边"不算
   - 如果没有，返回空数组 []

只返回 JSON：{{"answer": "...", "newly_discovered": [0, 1], "reasoning": "简短解释"}}"""
    return _chat_json(prompt)


def load_puzzles() -> list[dict]:
    if not PUZZLES_FILE.exists():
        return []
    try:
        data = json.loads(PUZZLES_FILE.read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except json.JSONDecodeError:
        return []
