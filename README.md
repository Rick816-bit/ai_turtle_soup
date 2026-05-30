# 🐢 AI 海龟汤

由大模型主持的海龟汤游戏。开发者给出汤面 + 汤底，AI 自动提炼"关键要点"，玩家提问，AI 用 **是 / 不是 / 是也不是 / 无关** 回答，并判断哪些要点被揭示。猜出全部要点即胜。

提供两种玩法：

- **CLI 版**（`python main.py`）—— 终端玩
- **Web 版**（`python server.py`）—— 浏览器玩，可部署成 app

## 安装

```powershell
pip install -r requirements.txt
```

首次运行 CLI 会引导你输入 DeepSeek API key 并保存到 `.env`；之后 Web 版也会自动读取。

## CLI 玩法

```powershell
python main.py
```

启动后显示题库菜单：
- 输入编号选定一题
- 输入 `r` 随机
- 输入 `0` 自己出题

游戏中可用 `progress` 查看进度、`giveup` 直接看汤底、`quit` 退出。

## Web 玩法

```powershell
python server.py
```

打开浏览器访问 <http://localhost:8000>。点题目卡片即可开局；右上方有"随机一道"和"自己出题"按钮。

## 项目结构

```
turtle_soup/
├── game.py            # 核心逻辑（模型调用、要点提取、判答、题库）
├── main.py            # CLI 入口
├── server.py          # FastAPI 后端 + 静态托管前端
├── web/
│   └── index.html     # 单页前端（原生 JS）
├── puzzles.json       # 内置 10 道经典题
├── requirements.txt
├── .env               # API key（自动生成，已 gitignore）
├── .gitignore
└── README.md
```

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/puzzles` | 列出题库（id + title） |
| POST | `/api/games` | 开局，body `{puzzle_id}` 或 `{surface, bottom}` |
| GET | `/api/games/{gid}` | 查询当前进度 |
| POST | `/api/games/{gid}/ask` | 提问，body `{question}` |
| POST | `/api/games/{gid}/giveup` | 弃权看汤底 |

## 后续可做的事（如果要正式上线）

- 当前 web 版的游戏状态存在**内存**里，服务器重启会丢；正式用需要换 Redis 或 SQLite
- 没有用户系统、没有速率限制，部署到公网前一定要加 —— 否则任何人都能消耗你的 DeepSeek 额度
- 部署：FastAPI 可直接打包到 Render / Railway / Fly.io；前端是纯静态，跟后端同源不用额外处理
- 想要桌面 app：在此基础上用 Tauri 或 Electron 套壳即可

## 注意

API key 写在服务器端 `.env`，不会下发到浏览器。不过本地 demo 没有任何 auth，请勿暴露到公网。
