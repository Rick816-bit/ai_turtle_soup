# AI 海龟汤

由大模型主持的海龟汤游戏。玩家阅读汤面后向 AI 提问，AI 只用 **是 / 不是 / 是也不是 / 无关** 裁决，并判断哪些关键要点已经被玩家猜中。猜出全部要点即胜。

现在内置题库已扩展为 **20 道**，每题包含分类、难度、标签和预设关键要点；Web 首页可以按分类筛选题目。

## 功能

- CLI 版：`python main.py`
- Web 版：`python server.py`
- 内置题分类：经典推理、清汤日常、犯罪悬疑、惊悚怪谈、职业机关、身份错位
- 内置题使用预设 `key_points`，开局不再重复调用模型提取要点
- 自定义出题仍会调用模型自动提取关键要点
- Web 版支持分类筛选、当前分类随机、提示、放弃查看汤底
- 基础滥用防护：输入长度限制、单局提问上限、内存局数上限、TTL、POST 限流

## 安装

```powershell
pip install -r requirements.txt
```

配置 DeepSeek API key：

```powershell
$env:DEEPSEEK_API_KEY="sk-..."
```

也可以首次运行 CLI 时按提示保存到 `.env`。`.env` 已在 `.gitignore` 中。

可选环境变量：

| 变量 | 默认值 | 说明 |
| --- | --- | --- |
| `DEEPSEEK_API_KEY` | 无 | 模型调用必需 |
| `TURTLE_MODEL` | `deepseek-v4-pro` | 模型名 |
| `TURTLE_BASE_URL` | `https://api.deepseek.com/anthropic` | Anthropic 兼容接口地址 |
| `PORT` | `8000` | Web 服务端口 |
| `TURTLE_MAX_QUESTION_LEN` | `200` | 单次提问最大长度 |
| `TURTLE_MAX_QUESTIONS_PER_GAME` | `50` | 单局最大提问数 |
| `TURTLE_MAX_HINTS_PER_GAME` | `3` | 单局提示次数 |
| `TURTLE_MAX_GAMES_IN_MEMORY` | `500` | 内存中最多保留局数 |
| `TURTLE_GAME_TTL_SECONDS` | `86400` | 游戏状态保留时间 |
| `TURTLE_RATE_LIMIT_WINDOW` | `60` | 限流窗口秒数 |
| `TURTLE_RATE_LIMIT_MAX` | `30` | 每个窗口最多 POST 次数 |
| `CORS_ALLOW_ORIGINS` | 空 | 逗号分隔的跨域来源 |
| `TRUST_X_FORWARDED_FOR` | 空 | 部署在可信反向代理后才设为 `true` |

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

打开浏览器访问 <http://localhost:8000>。首页可以选择分类、随机抽题或自己出题。

没有 API key 时服务端仍能启动并展示题库；但提问、自定义出题和 AI 提示需要 API key。

## 题库格式

`puzzles.json` 是一个数组，每题结构如下：

```json
{
  "id": 1,
  "title": "题目名",
  "category": "经典推理",
  "difficulty": "中等",
  "tags": ["清汤", "本格"],
  "surface": "汤面",
  "bottom": "汤底",
  "key_points": ["玩家需要猜出的关键要点"]
}
```

内置题建议手写 `key_points`，这样开局更快、成本更低、同一题的胜利条件也更稳定。自定义题没有 `key_points` 时会自动调用模型提取。

## 项目结构

```text
turtle_soup/
├── game.py            # 核心逻辑：模型调用、判答、提示、题库加载
├── main.py            # CLI 入口
├── server.py          # FastAPI 后端 + 静态托管前端
├── web/
│   └── index.html     # 单页前端（原生 JS）
├── puzzles.json       # 内置 20 道分类题库
├── requirements.txt
├── .env               # API key（自动生成，已 gitignore）
├── .gitignore
└── README.md
```

## HTTP 接口

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/puzzles` | 列出题库元信息：`id/title/category/difficulty/tags` |
| POST | `/api/games` | 开局，body `{ "puzzle_id": 1 }` 或 `{ "surface": "...", "bottom": "..." }` |
| GET | `/api/games/{gid}` | 查询当前进度 |
| POST | `/api/games/{gid}/ask` | 提问，body `{ "question": "..." }` |
| POST | `/api/games/{gid}/hint` | 获取一个方向提示，不直接计入进度 |
| POST | `/api/games/{gid}/giveup` | 弃权并查看完整汤底 |

## 分类参考

分类设计参考了海龟汤常见术语和 lateral thinking puzzle 的常见组织方式：清汤/红汤/黑汤、本格/变格，以及 crime、family、plot twist、creepy 等标签式分类。新增题目为项目内原创或改写题型，没有直接搬运网页原文。
