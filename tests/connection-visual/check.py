"""CI-only production component layout checks; synthetic state, not device proof."""
import json
import os
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
                for phase in ("waiting_for_ready", "existing_routes_only", "refresh_required", "no_route", "test_failed", "address_prepared", "peer_verified"):
                    page = browser.new_page(viewport={"width":width,"height":900})
                    page.add_init_script("Object.defineProperty(navigator, 'clipboard', {value:{writeText:async()=>{throw new Error('denied')}}})")
                    page.goto("http://127.0.0.1:1421/?phase="+phase)
                    page.get_by_text("Mesh Chat version", exact=False).wait_for()
                    page.wait_for_function("document.querySelector('[role=status]') !== null")
                    if scale == 2:
                        page.evaluate("""() => {
                          const sizes = [...document.querySelectorAll('body *')].map(e => [e, parseFloat(getComputedStyle(e).fontSize)]);
                          sizes.forEach(([e,size]) => e.style.fontSize = `${size * 2}px`);
                        }""")
                    page.get_by_role("button",name="Copy diagnostics",exact=True).click()
                    page.get_by_text("Copy is unavailable.",exact=False).wait_for()
                    overflow = page.evaluate("""() => [...document.querySelectorAll('.dialog, .guided-connection, button, textarea')]
                      .filter(e => {const r=e.getBoundingClientRect();return r.width && (r.left < -1 || r.right > innerWidth+1 || e.scrollWidth > e.clientWidth+2);})
                      .map(e => e.tagName+':'+e.className)""")
                    name = f"{width}-{scale}x-{phase}"
                    page.screenshot(path=str(output/(name+".png")))
                    results.append({"case":name,"overflow":overflow})
                    page.close()
    finally:
        browser.close()
        (output/"results.json").write_text(json.dumps(results,indent=2))
assert len(results) == 42 and not any(row["overflow"] for row in results), results
