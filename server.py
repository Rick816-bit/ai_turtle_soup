"""海龟汤 Web 服务端（FastAPI）。

启动:
    python server.py
然后浏览器访问 http://localhost:8000

接口:
    GET  /api/puzzles                列出题库（仅 id + title）
    POST /api/games                  开局
    POST /api/games/{gid}/ask        提问
    POST /api/games/{gid}/giveup     弃权看汤底
    GET  /api/games/{gid}            查询当前进度
"""

import uuid
from dataclasses import dataclass, field
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

import game

WEB_DIR = Path(__file__).parent / "web"

app = FastAPI(title="海龟汤 API")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)


@dataclass
class GameState:
    surface: str
    bottom: str
    key_points: list[str]
    discovered: set[int] = field(default_factory=set)
    history: list[tuple[str, str]] = field(default_factory=list)
    turn: int = 0
    finished: bool = False


games: dict[str, GameState] = {}


class StartGameReq(BaseModel):
    puzzle_id: int | None = None
    surface: str | None = None
    bottom: str | None = None


class AskReq(BaseModel):
    question: str


@app.get("/api/puzzles")
def list_puzzles():
    return [{"id": p["id"], "title": p["title"]} for p in game.load_puzzles()]


@app.post("/api/games")
def start_game(req: StartGameReq):
    if req.puzzle_id is not None:
        puzzles = game.load_puzzles()
        match = next((p for p in puzzles if p["id"] == req.puzzle_id), None)
        if not match:
            raise HTTPException(404, "题目不存在")
        surface, bottom = match["surface"], match["bottom"]
    elif req.surface and req.bottom:
        surface, bottom = req.surface.strip(), req.bottom.strip()
    else:
        raise HTTPException(400, "需要提供 puzzle_id 或 surface+bottom")

    try:
        key_points = game.extract_key_points(surface, bottom)
    except Exception as e:
        raise HTTPException(500, f"提取要点失败：{e}")

    gid = uuid.uuid4().hex[:8]
    games[gid] = GameState(surface=surface, bottom=bottom, key_points=key_points)
    return {
        "game_id": gid,
        "surface": surface,
        "total_points": len(key_points),
    }


@app.get("/api/games/{gid}")
def get_game(gid: str):
    state = games.get(gid)
    if not state:
        raise HTTPException(404, "游戏不存在")
    return {
        "game_id": gid,
        "surface": state.surface,
        "turn": state.turn,
        "progress": [len(state.discovered), len(state.key_points)],
        "finished": state.finished,
        "history": [{"q": q, "a": a} for q, a in state.history],
        "discovered": [
            {"index": i, "text": state.key_points[i]} for i in sorted(state.discovered)
        ],
        "bottom": state.bottom if state.finished else None,
    }


@app.post("/api/games/{gid}/ask")
def ask(gid: str, req: AskReq):
    state = games.get(gid)
    if not state:
        raise HTTPException(404, "游戏不存在")
    if state.finished:
        raise HTTPException(400, "游戏已结束")
    if not req.question.strip():
        raise HTTPException(400, "问题不能为空")

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
    newly_items = []
    for idx in newly_idx:
        if isinstance(idx, int) and 0 <= idx < len(state.key_points) and idx not in state.discovered:
            state.discovered.add(idx)
            newly_items.append({"index": idx, "text": state.key_points[idx]})

    state.history.append((req.question, answer))
    if len(state.discovered) >= len(state.key_points):
        state.finished = True

    return {
        "turn": state.turn,
        "answer": answer,
        "newly_discovered": newly_items,
        "progress": [len(state.discovered), len(state.key_points)],
        "won": state.finished,
        "bottom": state.bottom if state.finished else None,
    }


@app.post("/api/games/{gid}/giveup")
def giveup(gid: str):
    state = games.get(gid)
    if not state:
        raise HTTPException(404, "游戏不存在")
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
      import os, uvicorn
      game.load_dotenv()
      port = int(os.environ.get("PORT", 8000))
      uvicorn.run(app, host="0.0.0.0", port=port)
