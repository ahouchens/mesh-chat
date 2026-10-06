const port = Number(process.argv[2] ?? "9223");
const shouldReload = !process.argv.includes("--no-reload");
const origin = `http://127.0.0.1:${port}`;

async function targets() {
  const response = await fetch(`${origin}/json/list`);
  if (!response.ok) throw new Error(`DevTools target listing failed: ${response.status}`);
  return response.json();
}

const deadline = Date.now() + 15_000;
let target;
while (Date.now() < deadline) {
  try {
    const values = await targets();
    target = values.find((value) => value.type === "page") ?? values[0];
    if (target?.webSocketDebuggerUrl) break;
  } catch {
    // The WebView debugging endpoint can appear shortly after the app process.
  }
  await new Promise((resolve) => setTimeout(resolve, 250));
}
if (!target?.webSocketDebuggerUrl) throw new Error("No debuggable WebView target appeared");

const socket = new WebSocket(target.webSocketDebuggerUrl);
const pending = new Map();
const exceptions = [];
const consoleMessages = [];
let nextId = 1;

socket.addEventListener("message", (event) => {
  const value = JSON.parse(String(event.data));
  if (value.id) {
    const operation = pending.get(value.id);
    if (operation) {
      pending.delete(value.id);
      if (value.error) operation.reject(new Error(value.error.message));
      else operation.resolve(value.result);
    }
    return;
  }
  if (value.method === "Runtime.exceptionThrown") {
    exceptions.push(value.params.exceptionDetails);
  } else if (value.method === "Runtime.consoleAPICalled") {
    consoleMessages.push(value.params);
  } else if (value.method === "Log.entryAdded") {
    consoleMessages.push(value.params.entry);
  }
});

await new Promise((resolve, reject) => {
  socket.addEventListener("open", resolve, { once: true });
  socket.addEventListener("error", reject, { once: true });
});

function call(method, params = {}) {
  const id = nextId++;
  socket.send(JSON.stringify({ id, method, params }));
  return new Promise((resolve, reject) => pending.set(id, { resolve, reject }));
}

await call("Runtime.enable");
await call("Log.enable");
await call("Page.enable");
if (shouldReload) await call("Page.reload", { ignoreCache: true });
await new Promise((resolve) => setTimeout(resolve, shouldReload ? 10_000 : 2_000));

const evaluated = await call("Runtime.evaluate", {
  expression: `JSON.stringify({
    url: location.href,
    readyState: document.readyState,
    title: document.title,
    bodyText: document.body?.innerText?.slice(0, 2000) ?? "",
    rootHtml: document.getElementById("root")?.innerHTML?.slice(0, 2000) ?? "",
    layout: (() => {
      const conversation = document.querySelector(".conversation");
      const header = document.querySelector(".conversation__header");
      const banner = document.querySelector(".connection-banner");
      const messages = document.querySelector(".message-list");
      const composer = document.querySelector(".composer");
      const height = (element) => element ? Number(element.getBoundingClientRect().height.toFixed(2)) : null;
      return conversation ? {
        gridTemplateAreas: getComputedStyle(conversation).gridTemplateAreas,
        gridTemplateRows: getComputedStyle(conversation).gridTemplateRows,
        headerArea: header ? getComputedStyle(header).gridArea : null,
        bannerArea: banner ? getComputedStyle(banner).gridArea : null,
        messagesArea: messages ? getComputedStyle(messages).gridArea : null,
        composerArea: composer ? getComputedStyle(composer).gridArea : null,
        headerHeight: height(header),
        bannerHeight: height(banner),
        messagesHeight: height(messages),
        composerHeight: height(composer),
        renderedMessages: document.querySelectorAll(".message").length
      } : null;
    })()
  })`,
  returnByValue: true,
});

const simplifyException = (value) => ({
  text: value.text,
  description: value.exception?.description,
  url: value.url,
  lineNumber: value.lineNumber,
  columnNumber: value.columnNumber,
  stack: value.stackTrace?.callFrames?.slice(0, 8),
});

console.log(JSON.stringify({
  target: { title: target.title, url: target.url },
  page: JSON.parse(evaluated.result.value),
  exceptions: exceptions.map(simplifyException),
  consoleMessages,
}, null, 2));
socket.close();
