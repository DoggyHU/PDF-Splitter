"""PDF Splitter entry point."""

import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)

from pdf_splitter.gui.app import run  # noqa: E402

if __name__ == "__main__":
    run()
