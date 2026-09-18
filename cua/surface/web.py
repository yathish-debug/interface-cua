from __future__ import annotations
import re
from playwright.sync_api import sync_playwright
from cua.surface.base import Surface
from cua.surface.types import Observation, Element, Action

# Accessibility roles we treat as actionable controls.
INTERACTIVE_ROLES = {
    "button", "link", "textbox", "searchbox", "combobox",
    "checkbox", "radio", "switch", "menuitem", "tab",
    "spinbutton", "slider",
}
# Roles that carry readable state (balances, errors, headings).
TEXT_ROLES = {
    "heading", "paragraph", "cell", "rowheader", "columnheader",
    "listitem", "alert", "status",
}


class WebSurface(Surface):
    def __init__(self, url: str, headed: bool = True):
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.launch(headless=not headed)
        self._page = self._browser.new_page()
        self._page.goto(url, wait_until="domcontentloaded")
        # ref -> (role, name) so act() can re-locate what observe() saw.
        self._ref_map: dict[str, tuple[str, str]] = {}
        self.last_locator: dict | None = None

    def observe(self) -> Observation:
        # Let transient loads settle without a blind sleep.
        try:
            self._page.wait_for_load_state("networkidle", timeout=3000)
        except Exception:
            pass

        # ARIA snapshot = current accessibility-tree API. Returns YAML text.
        yaml_text = self._page.locator("body").aria_snapshot()
        elements: list[Element] = []
        texts: list[str] = []
        self._ref_map = {}

        for raw in yaml_text.splitlines():
            line = raw.strip()
            if not line.startswith("-"):
                continue
            body = line[1:].strip()
            if not body:
                continue

            # A pure text node: `- text: some content`
            if body.startswith("text:"):
                content = body[5:].strip().strip('"')
                if content:
                    texts.append(content)
                continue

            # A bare quoted string node: `- "some text"`
            if body.startswith('"'):
                content = body.strip('"').rstrip(":").strip()
                if content:
                    texts.append(content)
                continue

            # A `role "name" [attrs]` node
            m = re.match(r'([A-Za-z]+)\s*(?:"([^"]*)")?', body)
            if not m:
                continue
            role = m.group(1)
            name = (m.group(2) or "").strip()

            if role in INTERACTIVE_ROLES:
                ref = f"e{len(elements)}"
                elements.append(Element(ref=ref, role=role, name=name, value=None))
                self._ref_map[ref] = (role, name)
            elif name and role in TEXT_ROLES:
                texts.append(name)

        # De-dup text while preserving order.
        seen, deduped = set(), []
        for t in texts:
            if t not in seen:
                seen.add(t)
                deduped.append(t)

        return Observation(
            url=self._page.url,
            title=self._page.title(),
            elements=elements,
            text=deduped,
        )

    def act(self, action: Action) -> None:
        if action.kind in ("click", "type"):
            if action.ref not in self._ref_map:
                raise ValueError(f"Unknown ref {action.ref!r} — observe() again first.")
            role, name = self._ref_map[action.ref]
            self.last_locator = {"role": role, "name": name}   # <-- durable identity for the recorder
            locator = self._page.get_by_role(role, name=name, exact=True)
            if locator.count() == 0:            # fallback: loosen exactness
                locator = self._page.get_by_role(role, name=name)
            target = locator.first
            target.wait_for(state="visible", timeout=5000)

            if action.kind == "click":
                target.click()
            else:  # type
                target.fill("")               # clear first for determinism
                target.fill(action.text or "")
        else:
            raise ValueError(f"Surface cannot execute action kind {action.kind!r}")

    def screenshot(self, path: str) -> None:
        self._page.screenshot(path=path, full_page=True)
    def url(self) -> str:
        return self.page.url

    def title(self) -> str:
        return self.page.title()

    def close(self) -> None:
        try:
            self._browser.close()
        finally:
            self._pw.stop()