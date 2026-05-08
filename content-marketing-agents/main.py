"""Точка входа CLI для AI Content Marketing Agents."""
from __future__ import annotations

import argparse
import logging
import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
log = logging.getLogger("main")


def cmd_research(args: argparse.Namespace) -> None:
    from agents.researcher import Researcher

    agent = Researcher()
    if args.input:
        agent.ingest_directory(Path(args.input))
    if args.url:
        agent.ingest_url(args.url)
    if args.interactive:
        agent.interactive()
    agent.write_report(Path("data/outputs/research_report.md"))


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="content-marketing-agents")
    sub = parser.add_subparsers(dest="command", required=True)

    p_research = sub.add_parser("research", help="Запустить агента-исследователя")
    p_research.add_argument("--input", type=str, help="Папка с документами")
    p_research.add_argument("--url", type=str, help="URL для парсинга")
    p_research.add_argument("--interactive", action="store_true", help="Интерактивный режим")
    p_research.set_defaults(func=cmd_research)

    return parser


def main() -> None:
    parser = build_parser()
    args = parser.parse_args()
    args.func(args)


if __name__ == "__main__":
    main()
