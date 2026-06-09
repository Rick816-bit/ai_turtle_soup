"""海龟汤 Web 服务端（FastAPI）。

启动:
    python server.py
然后浏览器访问 http://localhost:8000

接口:
    GET  /api/puzzles                列出题库（仅 id + title）
    POST /api/games                  开局
    POST /api/games/{gid}/ask        提问
    POST /api/games/{gid}/hint       获取提示
    POST /api/games/{gid}/giveup     弃权看汤底
    GET  /api/games/{gid}            查询当前进度
"""

import os
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

import game

WEB_DIR = Path(__file__).parent / "web"

# 滥用防护参数（可通过环境变量覆盖）
MAX_QUESTIONS_PER_GAME = int(os.environ.get("TURTLE_MAX_QUESTIONS_PER_GAME", "50"))
MAX_GAMES_IN_MEMORY = int(os.environ.get("TURTLE_MAX_GAMES_IN_MEMORY", "500"))
GAME_TTL_SECONDS = int(os.environ.get("TURTLE_GAME_TTL_SECONDS", str(24 * 3600)))
RATE_LIMIT_WINDOW = int(os.environ.get("TURTLE_RATE_LIMIT_WINDOW", "60"))
RATE_LIMIT_MAX = int(os.environ.get("TURTLE_RATE_LIMIT_MAX", "30"))
MAX_HINTS_PER_GAME = int(os.environ.get("TURTLE_MAX_HINTS_PER_GAME", "3"))
TRUST_X_FORWARDED_FOR = os.environ.get("TRUST_X_FORWARDED_FOR", "").lower() in {
    "1",
    "true",
    "yes",
}

# 按 IP 记录最近请求时间戳，用作滑动窗口限流
_rate_log: dict[str, deque[float]] = defaultdict(deque)


app = FastAPI(title="海龟汤 API")

# 默认不开放 CORS（前后端同源）；如需跨域，设环境变量 CORS_ALLOW_ORIGINS=https://a.com,https://b.com
_cors_raw = os.environ.get("CORS_ALLOW_ORIGINS", "").strip()
_cors_origins = [o.strip() for o in _cors_raw.split(",") if o.strip()] if _cors_raw else []
app.add_middleware(
    CORSMiddleware,
    allow_origins=_cors_origins,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def rate_limit(request: Request, call_next):
    """对所有 /api/ 下的 POST 请求按 IP 滑动窗口限流。"""
    if request.method == "POST" and request.url.path.startswith("/api/"):
        ip = request.client.host if request.client else "unknown"
        # 只有明确处在可信反向代理后，才使用 X-Forwarded-For。
        fwd = request.headers.get("x-forwarded-for") if TRUST_X_FORWARDED_FOR else None
        if fwd:
            ip = fwd.split(",")[0].strip()

        now = time.time()
        log = _rate_log[ip]
        while log and now - log[0] > RATE_LIMIT_WINDOW:
            log.popleft()
        if len(log) >= RATE_LIMIT_MAX:
            return JSONResponse(
                {"detail": f"请求过于频繁，请稍后再试（每分钟最多 {RATE_LIMIT_MAX} 次）"},
                status_code=429,
            )
        log.append(now)
    return await call_next(request)


@dataclass
class GameState:
    surface: str
    bottom: str
    key_points: list[str]
    discovered: set[int] = field(default_factory=set)
    discovered_summaries: dict[int, str] = field(default_factory=dict)
    history: list[tuple[str, str]] = field(default_factory=list)
    turn: int = 0
    hints_used: int = 0
    finished: bool = False
    created_at: float = field(default_factory=time.time)


games: dict[str, GameState] = {}


def _evict_games() -> None:
    """删除过期游戏；超出数量上限时按创建时间清理最早的。"""
    now = time.time()
    expired = [g for g, st in games.items() if now - st.created_at > GAME_TTL_SECONDS]
    for g in expired:
        games.pop(g, None)
    if len(games) > MAX_GAMES_IN_MEMORY:
        oldest = sorted(games.items(), key=lambda kv: kv[1].created_at)
        for g, _ in oldest[: len(games) - MAX_GAMES_IN_MEMORY]:
            games.pop(g, None)


def _maybe_finish(state: GameState) -> None:
    """所有要点都已揭示 → 结束游戏。"""
    if len(state.discovered) >= len(state.key_points):
        state.finished = True


def _get_state(gid: str) -> GameState:
    _evict_games()
    state = games.get(gid)
    if not state:
        raise HTTPException(404, "游戏不存在")
    return state


class StartGameReq(BaseModel):
    puzzle_id: int | None = None
    surface: str | None = Field(default=None, max_length=game.MAX_SURFACE_LEN)
    bottom: str | None = Field(default=None, max_length=game.MAX_BOTTOM_LEN)


class AskReq(BaseModel):
    question: str = Field(min_length=1, max_length=game.MAX_QUESTION_LEN)


@app.get("/api/puzzles")
def list_puzzles():
    puzzles = []
    for p in game.load_puzzles():
        puzzles.append(
            {
                "id": p["id"],
                "title": p["title"],
                "category": p.get("category", "未分类"),
                "difficulty": p.get("difficulty", "未知"),
                "tags": p.get("tags", []),
            }
        )
    return puzzles


@app.post("/api/games")
def start_game(req: StartGameReq):
    match = None
    if req.puzzle_id is not None:
        puzzles = game.load_puzzles()
        match = next((p for p in puzzles if p["id"] == req.puzzle_id), None)
        if not match:
            raise HTTPException(404, "题目不存在")
        surface, bottom = match["surface"], match["bottom"]
    elif req.surface and req.bottom:
        surface, bottom = req.surface.strip(), req.bottom.strip()
        if not surface or not bottom:
            raise HTTPException(400, "汤面和汤底不能为空")
    else:
        raise HTTPException(400, "需要提供 puzzle_id 或 surface+bottom")

    _evict_games()

    key_points = game.normalize_key_points(match.get("key_points")) if match else []
    if not key_points:
        try:
            key_points = game.extract_key_points(surface, bottom)
        except Exception as e:
            raise HTTPException(500, f"提取要点失败：{e}")

    gid = uuid.uuid4().hex
    games[gid] = GameState(surface=surface, bottom=bottom, key_points=key_points)
    return {
        "game_id": gid,
        "surface": surface,
        "category": match.get("category") if match else "自定义",
        "difficulty": match.get("difficulty") if match else "自定义",
        "total_points": len(key_points),
        "max_hints": MAX_HINTS_PER_GAME,
    }


@app.get("/api/games/{gid}")
def get_game(gid: str):
    state = _get_state(gid)
    return {
        "game_id": gid,
        "surface": state.surface,
        "turn": state.turn,
        "progress": [len(state.discovered), len(state.key_points)],
        "finished": state.finished,
        "history": [{"q": q, "a": a} for q, a in state.history],
        "discovered": [
            {
                "index": i,
                "text": state.discovered_summaries.get(i, state.key_points[i]),
            }
            for i in sorted(state.discovered)
        ],
        "bottom": state.bottom if state.finished else None,
    }


@app.post("/api/games/{gid}/ask")
def ask(gid: str, req: AskReq):
    state = _get_state(gid)
    if state.finished:
        raise HTTPException(400, "游戏已结束")
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")
    if state.turn >= MAX_QUESTIONS_PER_GAME:
        raise HTTPException(
            429, f"本局已达提问上限 ({MAX_QUESTIONS_PER_GAME})，请开新局"
        )

    state.turn += 1
    try:
        result = game.judge(
            state.surface, state.bottom, state.key_points,
            state.discovered, state.history, req.question,
        )
    except Exception as e:
        state.turn -= 1
        raise HTTPException(500, f"模型调用失败：{e}")

    answer = result.get("answer", "（无）")
    newly_idx = result.get("newly_discovered", []) or []
    newly_summaries = result.get("newly_summaries") or {}
    newly_items = []
    for idx in newly_idx:
        if isinstance(idx, int) and 0 <= idx < len(state.key_points) and idx not in state.discovered:
            state.discovered.add(idx)
            summary = newly_summaries.get(idx) or state.key_points[idx]
            state.discovered_summaries[idx] = summary
            newly_items.append({"index": idx, "text": summary})

    state.history.append((req.question, answer))
    _maybe_finish(state)

    return {
        "turn": state.turn,
        "answer": answer,
        "newly_discovered": newly_items,
        "progress": [len(state.discovered), len(state.key_points)],
        "won": state.finished,
        "bottom": state.bottom if state.finished else None,
    }


@app.post("/api/games/{gid}/hint")
def hint(gid: str):
    """给出一个未揭示要点的方向提示（不直接计入进度）。"""
    state = _get_state(gid)
    if state.finished:
        raise HTTPException(400, "游戏已结束")
    if state.hints_used >= MAX_HINTS_PER_GAME:
        raise HTTPException(
            429, f"本局提示次数已用完（上限 {MAX_HINTS_PER_GAME}）"
        )

    undiscovered = [i for i in range(len(state.key_points)) if i not in state.discovered]
    if not undiscovered:
        _maybe_finish(state)
        raise HTTPException(400, "已无可提示要点")

    idx = undiscovered[0]
    try:
        summary = game.summarize_point(
            state.surface, state.bottom, state.key_points, idx
        )
    except Exception:
        summary = state.key_points[idx]

    state.hints_used += 1

    return {
        "index": idx,
        "text": summary,
        "progress": [len(state.discovered), len(state.key_points)],
        "hints_left": MAX_HINTS_PER_GAME - state.hints_used,
        "won": state.finished,
    }


@app.post("/api/games/{gid}/giveup")
def giveup(gid: str):
    state = _get_state(gid)
    state.finished = True
    return {
        "bottom": state.bottom,
        "key_points": [
            {"index": i, "text": kp, "discovered": i in state.discovered}
            for i, kp in enumerate(state.key_points)
        ],
    }


# 把前端 web/ 静态目录挂到根路径
if WEB_DIR.exists():
    app.mount("/", StaticFiles(directory=WEB_DIR, html=True), name="web")


if __name__ == "__main__":
    import sys

    import uvicorn

    game.load_dotenv()
    try:
        game.get_client()
    except RuntimeError as e:
        print(f"提示：{e}；题库页面仍可打开，提问和自定义出题需要 API key。", file=sys.stderr)
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
