"""海龟汤 CLI 入口。游戏逻辑全部在 game.py。"""

import os
import random
import sys

import game


def ensure_api_key_interactive() -> None:
    """CLI 专用：没有 key 就交互式提示，并可选保存到 .env。"""
    game.load_dotenv()
    if os.environ.get("DEEPSEEK_API_KEY", "").strip():
        return

    print("未检测到 DEEPSEEK_API_KEY。")
    try:
        key = input("请输入你的 DeepSeek API key（sk-...）: ").strip()
    except (EOFError, KeyboardInterrupt):
        print("\n已取消。")
        sys.exit(1)
    if not key:
        print("key 不能为空。", file=sys.stderr)
        sys.exit(1)

    save = input(f"是否保存到 {game.ENV_FILE.name} 以便下次自动加载？[Y/n] ").strip().lower()
    if save in ("", "y", "yes"):
        game.save_to_dotenv("DEEPSEEK_API_KEY", key)
        print(f"已写入 {game.ENV_FILE}（请勿提交到 git）")
    os.environ["DEEPSEEK_API_KEY"] = key


def read_multiline(prompt: str) -> str:
    print(prompt + "（多行输入，空行结束）")
    lines: list[str] = []
    while True:
        try:
            line = input()
        except EOFError:
            break
        if line == "":
            if lines:
                break
            continue
        lines.append(line)
    return "\n".join(lines).strip()


def select_puzzle(puzzles: list[dict]) -> tuple[str, str, list[str] | None]:
    print("\n📚 题库：")
    for p in puzzles:
        print(f"  [{p['id']:>2}] {p['title']}")
    print(f"  [ 0] 自己输入汤面/汤底")
    print(f"  [ r] 随机选一道")

    while True:
        try:
            choice = input(f"\n请选择 (1-{len(puzzles)} / 0 / r): ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print("\n已取消。")
            sys.exit(0)

        if choice == "r":
            p = random.choice(puzzles)
            print(f"🎲 随机选中：[{p['id']}] {p['title']}")
            return p["surface"], p["bottom"], game.normalize_key_points(p.get("key_points"))
        if choice == "0":
            surface = read_multiline("请输入【汤面】:")
            print()
            bottom = read_multiline("请输入【汤底】:")
            if surface and bottom:
                return surface, bottom, None
            print("汤面和汤底都不能为空，请重新选择。")
            continue
        try:
            n = int(choice)
        except ValueError:
            print("输入无效，请输入数字或 r。")
            continue
        for p in puzzles:
            if p["id"] == n:
                print(f"已选择：[{p['id']}] {p['title']}")
                return p["surface"], p["bottom"], game.normalize_key_points(p.get("key_points"))
        print("编号不存在，请重选。")


def play(surface: str, bottom: str, key_points: list[str] | None = None) -> None:
    if key_points:
        print("\n正在读取题库关键要点……\n")
    else:
        print("\n正在分析汤底、提取关键要点……\n")
        key_points = game.extract_key_points(surface, bottom)

    print(f"本局共 {len(key_points)} 个要点待揭示。")
    print("=" * 60)
    print("游戏开始！向 AI 提问，它会回答：是 / 不是 / 是也不是 / 无关")
    print("输入 'quit' 退出，'progress' 查看进度，'giveup' 直接看汤底")
    print("=" * 60)
    print(f"\n【汤面】{surface}\n")

    discovered: set[int] = set()
    discovered_summaries: dict[int, str] = {}
    history: list[tuple[str, str]] = []
    turn = 0

    while len(discovered) < len(key_points):
        turn += 1
        try:
            question = input(f"[第 {turn} 问] 你的问题: ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\n游戏中断。")
            return
        if not question:
            turn -= 1
            continue
        if len(question) > game.MAX_QUESTION_LEN:
            print(f"  ⚠️ 问题过长（最多 {game.MAX_QUESTION_LEN} 字），请精简后重试。\n")
            turn -= 1
            continue
        cmd = question.lower()
        if cmd == "quit":
            print("再见。")
            return
        if cmd == "progress":
            print(f"  进度：{len(discovered)}/{len(key_points)}")
            for i in range(len(key_points)):
                mark = "✓" if i in discovered else "·"
                shown = discovered_summaries.get(i, "（未揭示）") if i in discovered else "（未揭示）"
                print(f"   {mark} [{i+1}] {shown}")
            print()
            turn -= 1
            continue
        if cmd == "giveup":
            break

        try:
            result = game.judge(surface, bottom, key_points, discovered, history, question)
        except Exception as e:
            print(f"  ⚠️ 调用出错：{e}，请重试。\n")
            turn -= 1
            continue

        answer = result.get("answer", "（无）")
        newly = result.get("newly_discovered", []) or []
        newly_summaries = result.get("newly_summaries") or {}
        print(f"  AI: {answer}")
        for idx in newly:
            if isinstance(idx, int) and 0 <= idx < len(key_points) and idx not in discovered:
                discovered.add(idx)
                summary = newly_summaries.get(idx) or key_points[idx]
                discovered_summaries[idx] = summary
                print(f"  ✨ 揭示要点 {idx+1}/{len(key_points)}：{summary}")
        print(f"  [进度 {len(discovered)}/{len(key_points)}]\n")
        history.append((question, answer))

    print("=" * 60)
    if len(discovered) >= len(key_points):
        print(f"🎉 恭喜！你用了 {turn} 个问题猜出了全部要点！")
    else:
        print("游戏结束（弃权）。")
    print("=" * 60)
    print(f"\n【完整汤底】\n{bottom}\n")


def main() -> None:
    ensure_api_key_interactive()

    print("=" * 60)
    print("🐢  AI 海龟汤  Demo  (DeepSeek)")
    print("=" * 60)

    puzzles = game.load_puzzles()
    if puzzles:
        surface, bottom, key_points = select_puzzle(puzzles)
    else:
        print("（未找到 puzzles.json，进入自定义模式）\n")
        surface = read_multiline("请输入【汤面】:")
        print()
        bottom = read_multiline("请输入【汤底】:")
        key_points = None

    if not surface or not bottom:
        print("汤面和汤底都不能为空。", file=sys.stderr)
        sys.exit(1)

    play(surface, bottom, key_points)


if __name__ == "__main__":
    main()
