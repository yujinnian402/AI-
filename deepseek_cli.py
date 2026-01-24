from dotenv import load_dotenv
import os
import argparse
from deepseek_client import DeepSeekConfig, DeepSeekClient

load_dotenv()

def print_usage(resp: dict):
    usage = resp.get("usage")
    if not usage:
        print("\n[usage] (no usage field in response)")
        return
    # 兼容不同返回字段：把 usage 里所有键值都打印出来
    items = "  ".join([f"{k}={v}" for k, v in usage.items()])
    print(f"\n[usage] {items}")


def main():
    parser = argparse.ArgumentParser(description="DeepSeek terminal chat (basic)")
    parser.add_argument("--model", default="deepseek-chat", help="e.g. deepseek-chat / deepseek-reasoner",metavar="MODEL_NAME")
    parser.add_argument("--system", default="", help="system prompt (background instruction)")
    parser.add_argument("--temp", type=float, default=0.7, help="temperature")
    parser.add_argument("--top_p", type=float, default=0.9, help="top_p")
    parser.add_argument("--max_tokens", type=int, default=2000, help="max_tokens")
    parser.add_argument("--show-usage", action="store_true", help="print token usage metrics")
    args = parser.parse_args()

    api_key = os.environ.get("DEEPSEEK_API_KEY", "")
    if not api_key:
        raise RuntimeError("没有检测到环境变量 DEEPSEEK_API_KEY，请先 export DEEPSEEK_API_KEY=...")

    cfg = DeepSeekConfig(
        api_key=api_key,
        model=args.model,
        temperature=args.temp,
        top_p=args.top_p,
        max_tokens=args.max_tokens,
    )
    client = DeepSeekClient(cfg)

    # 终端输入一行 prompt（单轮版本）
    user_text = input("The husband of Miss Lara Croft，please input> ").strip()
    if not user_text:
        print("Empty input. Bye.")
        return

    messages = []
    if args.system:
        messages.append({"role": "system", "content": args.system})
    messages.append({"role": "user", "content": user_text})

    resp = client.chat(messages)
    assistant_msg = resp["choices"][0]["message"]

    print("\nLara Croft's AGI companion> " + assistant_msg.get("content", ""))

    # reasoner 可能带 reasoning_content（你想看就打开）
    if "reasoning_content" in assistant_msg and assistant_msg["reasoning_content"]:
        print("\n[reasoning_content]\n" + assistant_msg["reasoning_content"])

    if args.show_usage:
        print_usage(resp)


if __name__ == "__main__":
    main()
