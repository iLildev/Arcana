"""Interactive REPL for the Builder Agent — test without Telegram.

Usage::

    python -m zerobot.agents.cli_test [--user USER_ID]

Type ``/reset`` to wipe the workspace + history. ``/quit`` to exit.
"""

from __future__ import annotations

import argparse
import asyncio
import logging
import sys

from zerobot.agents.builder_agent import BuilderAgent


async def progress(line: str) -> None:
    """Print one progress line as it streams from the agent."""
    sys.stdout.write(f"  · {line}\n")
    sys.stdout.flush()


async def main() -> None:
    """Entry point — parse args, create the agent, and serve the REPL."""
    parser = argparse.ArgumentParser(description="Builder Agent REPL")
    parser.add_argument("--user", default="cli-tester", help="user id for the session")
    parser.add_argument("--debug", action="store_true", help="verbose logging")
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.DEBUG if args.debug else logging.INFO,
        format="%(levelname)s %(name)s: %(message)s",
    )

    agent = BuilderAgent()
    print(f"Builder Agent ready (user={args.user}). Commands: /reset /quit")
    while True:
        try:
            line = input("\n> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in {"/quit", "/exit"}:
            break
        if line == "/reset":
            agent.reset(args.user)
            print("workspace + session reset.")
            continue

        result = await agent.run_turn(args.user, line, on_progress=progress)
        print(f"\n--- reply ---\n{result.reply}")
        print(
            f"\n[{result.iterations} iterations, {result.tool_calls} tool calls, "
            f"{result.input_tokens}+{result.output_tokens} tokens]"
        )


if __name__ == "__main__":
    asyncio.run(main())
