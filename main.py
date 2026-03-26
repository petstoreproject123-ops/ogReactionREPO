import logging
from master_bot import MasterBot

# ── Logging setup ──────────────────────────────────────────────────────────────
logging.basicConfig(
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    level=logging.INFO,
)

# Silence noisy httpx logs
logging.getLogger("httpx").setLevel(logging.WARNING)


def main():
    bot = MasterBot(config_path="config.json")
    bot.run()


if __name__ == "__main__":
    main()
