// Run through Playwright CLI against `uv run --extra dev python -m tests.preview`.
async (page) => {
  await page.unrouteAll({ behavior: "ignoreErrors" });
  const assert = (condition, message) => { if (!condition) throw new Error(message); };
  const requests = [];
  const errors = [];
  page.on("request", (request) => requests.push({
    method: request.method(), url: request.url(), headers: request.headers(),
  }));
  page.on("pageerror", (error) => errors.push(error.message));
  const button = page.locator("#limit-button");
  const waitMode = (mode) => page.waitForFunction(
    (value) => document.querySelector("#mode").textContent === value
      && !document.querySelector("#limit-button").disabled, mode,
  );

  await page.reload();
  await waitMode("Limited");
  await page.waitForResponse((r) => r.url().endsWith("/api/status"), { timeout: 5000 });
  assert(requests.filter((r) => r.method === "POST").length === 0, "Reload/poll must not POST");
  assert((await page.locator("#download").textContent()).includes("17.4"), "Download missing");
  assert((await page.locator("#upload").textContent()).includes("1.8"), "Upload missing");

  await page.route("**/api/limit/off", async (route) => {
    await page.waitForTimeout(600);
    await route.continue();
  });
  await button.click();
  assert(await button.isDisabled(), "Button must be disabled during POST");
  assert((await button.textContent()).includes("Applying..."), "Applying label missing");
  await button.evaluate((element) => { element.click(); element.click(); });
  await waitMode("Unlimited");
  assert(requests.filter((r) => r.method === "POST").length === 1, "Repeated clicks must not POST");
  assert(requests.find((r) => r.method === "POST").url.endsWith("/api/limit/off"), "Wrong explicit action");
  assert((await button.textContent()).includes("Enable speed limit"), "Wrong Unlimited button");
  await page.unroute("**/api/limit/off");

  await page.route("**/api/limit/on", (route) => route.fulfill({
    status: 503, contentType: "application/json",
    body: JSON.stringify({ online: false, error: "qBittorrent unavailable" }),
  }));
  await button.click();
  await page.waitForFunction(() => !document.querySelector("#notice").hidden
    && !document.querySelector("#limit-button").disabled);
  assert((await page.locator("#notice").textContent()).includes("Could not confirm"), "POST failure missing");
  assert((await page.locator("#mode").textContent()) === "Unlimited", "Failed POST changed displayed state");
  await page.unroute("**/api/limit/on");
  await button.click();
  await waitMode("Limited");

  await page.route("**/api/status", (route) => route.fulfill({
    status: 503, contentType: "application/json",
    body: JSON.stringify({ online: false, error: "qBittorrent unavailable" }),
  }));
  await page.waitForFunction(() => document.querySelector("#mode").textContent === "Offline");
  assert(await button.isDisabled(), "Offline button must be disabled");
  assert((await page.locator("#download").textContent()).includes("—"), "Stale speed shown offline");
  await page.screenshot({ path: "output/playwright/offline.png", fullPage: true });
  await page.unroute("**/api/status");
  await waitMode("Limited");

  await page.route("**/api/status", (route) => route.fulfill({
    status: 200, contentType: "text/html", body: "<html>TinyAuth sign in</html>",
  }));
  await page.waitForFunction(() => document.querySelector("#notice").textContent.includes("sign in"));
  assert(await button.isDisabled(), "Expired session must disable button");
  await page.unroute("**/api/status");
  await waitMode("Limited");

  const viewports = [
    { width: 1440, height: 960, name: "desktop" },
    { width: 390, height: 844, name: "iphone" },
    { width: 320, height: 568, name: "small" },
  ];
  for (const viewport of viewports) {
    await page.setViewportSize({ width: viewport.width, height: viewport.height });
    const dimensions = await page.evaluate(() => ({
      width: document.documentElement.scrollWidth,
      viewport: innerWidth,
      buttonHeight: document.querySelector("#limit-button").getBoundingClientRect().height,
    }));
    assert(dimensions.width <= dimensions.viewport, `Horizontal overflow: ${viewport.name}`);
    assert(dimensions.buttonHeight >= 44, "Button touch target too small");
    await page.screenshot({ path: `output/playwright/${viewport.name}.png`, fullPage: true });
  }
  assert(errors.length === 0, `JavaScript errors: ${errors.join(", ")}`);
  assert(requests.every((r) => r.url.startsWith("http://127.0.0.1:8000/")), "External browser request");
  assert(requests.every((r) => !("authorization" in r.headers)), "Authorization exposed to browser");
  const posts = requests.filter((r) => r.method === "POST");
  assert(posts.every((r) => r.headers["x-qbt-control"] === "1"), "CSRF header missing");
  return {
    result: "PASS", checked: ["GET-only reload and polling", "explicit off/on", "double clicks",
      "Applying disabled state", "POST failure", "offline recovery", "expired session", "same-origin requests",
      "no browser Authorization", "1440px/390px/320px layouts"],
    requests: requests.length, posts: posts.map((r) => r.url.split("/").pop()),
    screenshots: viewports.map((v) => `output/playwright/${v.name}.png`),
  };
}
