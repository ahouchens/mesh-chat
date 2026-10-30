"""CI-only production component layout checks; synthetic state, not device proof."""
import json
import os
import re
from pathlib import Path
from playwright.sync_api import sync_playwright

if os.environ.get("GITHUB_ACTIONS") != "true":
    raise SystemExit("Frontend qualification runs in GitHub Actions")
output = Path("dist/connection-layout")
output.mkdir(parents=True, exist_ok=True)
results = []
with sync_playwright() as playwright:
    browser = playwright.chromium.launch()
    try:
        for width in (360, 393, 1280):
            for scale in (1, 2):
                for phase in ("waiting_for_ready", "existing_routes_only", "refresh_required", "no_route", "test_failed", "address_prepared", "peer_verified", "contact-requests"):
                    page = browser.new_page(viewport={"width":width,"height":900})
                    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value:{writeText:async()=>{throw new Error('denied')}}})")
                    inbox = phase == "contact-requests"
                    page.goto("http://127.0.0.1:1421/?" + ("contact-requests" if inbox else "phase="+phase))
                    if inbox:
                        page.get_by_role("heading", name="Contact requests", exact=True).wait_for()
                    else:
                        page.get_by_text("Mesh Chat version", exact=False).wait_for()
                        page.wait_for_function("document.querySelector('[role=status]') !== null")
                    if scale == 2:
                        page.evaluate("""() => {
                          const sizes = [...document.querySelectorAll('body *')].map(e => [e, parseFloat(getComputedStyle(e).fontSize)]);
                          sizes.forEach(([e,size]) => e.style.fontSize = `${size * 2}px`);
                        }""")
                    if not inbox:
                        page.get_by_role("button",name="Copy diagnostics",exact=True).click()
                        page.get_by_text("Copy is unavailable.",exact=False).wait_for()
                    overflow = page.evaluate("""() => [...document.querySelectorAll('.dialog, .guided-connection, button, textarea')]
                      .filter(e => {const r=e.getBoundingClientRect();return r.width && (r.left < -1 || r.right > innerWidth+1 || e.scrollWidth > e.clientWidth+2);})
                      .map(e => e.tagName+':'+e.className)""")
                    name = f"{width}-{scale}x-{phase}"
                    page.screenshot(path=str(output/(name+".png")))
                    results.append({"case":name,"overflow":overflow})
                    page.close()
        for width in (360, 393, 1280):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            outside_requests = []
            page.on("request", lambda request: outside_requests.append(request.url)
                    if not request.url.startswith("http://127.0.0.1:1421/") else None)
            # Provider availability is not a deterministic CI prerequisite.
            # The actual provider rendering/playback check is documented separately.
            page.route("https://www.youtube-nocookie.com/**", lambda route: route.fulfill(
                content_type="text/html", body="<html><body>Provider frame fixture</body></html>"))
            page.route("https://platform.twitter.com/**", lambda route: route.fulfill(
                content_type="text/html", body="<html><body>Provider frame fixture</body></html>"))
            page.goto("http://127.0.0.1:1421/?links")
            page.get_by_role("button", name="Load preview", exact=True).first.wait_for()
            assert not outside_requests, outside_requests
            assert page.locator("iframe").count() == 0
            page.get_by_role("button", name="Load preview", exact=True).first.click()
            page.get_by_role("button", name="Load preview", exact=True).first.click()
            page.get_by_text("A short animated film — preview fixture", exact=True).wait_for()
            assert page.locator("iframe").count() == 0
            assert not outside_requests, outside_requests
            page.get_by_role("button", name="Try playing here", exact=True).click()
            page.get_by_role("button", name="Try interactive post", exact=True).click()
            assert page.locator("iframe").count() == 2
            overflow = page.evaluate("""() => [...document.querySelectorAll('.message-content, .link-preview, .link-preview button, .link-preview iframe')]
              .filter(e => {const r=e.getBoundingClientRect();return r.width && (r.left < -1 || r.right > innerWidth+1 || e.scrollWidth > e.clientWidth+2);})
              .map(e => e.tagName+':'+e.className)""")
            name = f"{width}-link-previews"
            page.screenshot(path=str(output/(name+".png")))
            results.append({"case": name, "overflow": overflow})
            page.get_by_role("button", name="Close YouTube preview", exact=True).click()
            page.get_by_role("button", name="Close X preview", exact=True).click()
            assert page.locator("iframe").count() == 0
            page.close()
        for width in (360, 393, 1280):
            page = browser.new_page(viewport={"width": width, "height": 1000})
            page_errors = []
            page.on("pageerror", lambda error: page_errors.append(str(error)))
            page.goto("http://127.0.0.1:1421/?workspace-settings")
            page.get_by_role("heading", name="Workspace settings", exact=True).wait_for()
            assert page.get_by_role("dialog").count() == 0
            for section in ("People", "History & retention", "General", "Devices", "Ownership & recovery", "Access points", "Connections"):
                if width <= 760 and section != "People":
                    page.get_by_role("button", name="All workspace settings", exact=True).click()
                page.get_by_role("navigation", name="Workspace settings sections").get_by_role("button", name=re.compile("^" + re.escape(section))).click()
                page.get_by_role("heading", name=section, exact=True).wait_for()
                overflow = page.evaluate("""() => [...document.querySelectorAll('.workspace-settings-page button, .workspace-settings-page input, .workspace-settings-page select, .workspace-settings-page textarea, .workspace-settings-page__content')]
                  .filter(e => {const r=e.getBoundingClientRect();return r.width && (r.left < -1 || r.right > innerWidth+1 || e.scrollWidth > e.clientWidth+2);})
                  .map(e => e.tagName+':'+e.className)""")
                name = f"{width}-workspace-{section.lower().replace(' ', '-').replace('&', 'and')}"
                page.screenshot(path=str(output/(name+".png")))
                results.append({"case": name, "overflow": overflow})
            assert not page_errors, page_errors
            page.close()
    finally:
        browser.close()
        (output/"results.json").write_text(json.dumps(results,indent=2))
assert len(results) == 72 and not any(row["overflow"] for row in results), results
