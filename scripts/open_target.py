"""Phase 0 smoke test: open the mock bank in a headed browser to prove
the target is reachable and drivable. Saves a first screenshot to evidence/."""
from pathlib import Path
from playwright.sync_api import sync_playwright

TARGET = "http://localhost:8000/"
EVIDENCE = Path("evidence")
EVIDENCE.mkdir(exist_ok=True)


def main():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)  # headed = you watch it
        page = browser.new_page()
        page.goto(TARGET)
        print("Page title:", page.title())
        page.screenshot(path=str(EVIDENCE / "phase0_home.png"))
        print("Saved -> evidence/phase0_home.png")
        input("Browser is open. Press Enter here to close it...")
        browser.close()


if __name__ == "__main__":
    main()