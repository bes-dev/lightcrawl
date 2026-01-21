"""
Scrape worker process.

Run with: python -m src.worker
Scale with: docker compose up -d --scale worker=N
"""
import logging
import signal
from concurrent.futures import ThreadPoolExecutor

from src.config import settings
from src.scraper.queue import (
    pop_task,
    save_result,
    get_cached_page,
    set_cached_page,
    add_to_dlq,
    pop_dlq_ready,
)
from src.scraper.extractor import fetch_and_extract, close_client

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger(__name__)

running = True


def handle_signal(signum, frame):
    global running
    logger.info("Shutdown signal received")
    running = False


def process_task(task: dict) -> None:
    """Process single scrape task with DLQ retry support."""
    job_id = task["job_id"]
    url = task["url"]
    attempt = task.get("attempt", 0)

    cached = get_cached_page(url)
    if cached:
        save_result(job_id, url, cached)
        logger.debug(f"[{job_id}] Cache hit: {url}")
        return

    content = fetch_and_extract(url)

    if not content:
        add_to_dlq(job_id, url, "Empty content", attempt)
        return

    set_cached_page(url, content)
    save_result(job_id, url, content)


def get_next_task() -> dict | None:
    """Get next task (DLQ first, then pending)."""
    dlq_task = pop_dlq_ready()
    if dlq_task:
        return dlq_task
    return pop_task(timeout=1)


def main():
    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    logger.info(f"Worker started (concurrency={settings.scrape_concurrency})")

    with ThreadPoolExecutor(max_workers=settings.scrape_concurrency) as executor:
        futures = {}

        while running:
            # Fill up to concurrency limit
            while len(futures) < settings.scrape_concurrency:
                task = get_next_task()
                if task is None:
                    break
                future = executor.submit(process_task, task)
                futures[future] = task

            # Collect completed
            done = [f for f in futures if f.done()]
            for f in done:
                task = futures[f]
                try:
                    f.result()
                except Exception as e:
                    logger.error(f"Task failed [{task.get('job_id')}] {task.get('url')}: {e}")
                del futures[f]

    # Drain remaining
    logger.info(f"Draining {len(futures)} remaining tasks...")
    for f in list(futures.keys()):
        try:
            f.result(timeout=30)
        except Exception:
            pass

    close_client()
    logger.info("Worker stopped")


if __name__ == "__main__":
    main()
