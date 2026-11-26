"""Main entry point for NPTU Discord Bot."""
from __future__ import annotations

import logging
import os
import sys

from dotenv import load_dotenv

from discord_bot import NptuBot
from NptuRequester import NptuRequester


def setup_logging() -> None:
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )
    logging.getLogger("httpx").setLevel(logging.WARNING)


def main() -> int:
    load_dotenv()
    setup_logging()

    token = os.getenv("DISCORD_TOKEN", "").strip()
    if not token:
        logging.error("缺少 DISCORD_TOKEN，請參考 .env.example 建立 .env 檔案。")
        return 1

    requester = NptuRequester()
    bot = NptuBot(requester=requester)
    bot.run(token)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
