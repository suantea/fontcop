// FontCop 桌面版主进程：spawn 内嵌 Python 后端，加载本地 web/ 界面。
const { app, BrowserWindow, shell } = require("electron");
const path = require("path");
const { spawn } = require("child_process");
const http = require("http");

const PORT = process.env.FONTOP_PORT || "8642";
const HOST = "127.0.0.1";

// 开发态（--no-pack）：用项目根目录；打包态：用 extraResources 目录
const PACKED = !process.argv.includes("--no-pack");
const RESOURCES = PACKED
  ? path.join(process.resourcesPath)
  : path.resolve(__dirname, "..");
const PY_RUNTIME = path.join(RESOURCES, "python-runtime", "bin", "python3");
const PROJECT = RESOURCES; // 含 src/ web/ fonts/ data/

let pyProc = null;
let mainWin = null;

function startBackend() {
  const env = {
    ...process.env,
    FONTOP_HOST: HOST,
    FONTOP_PORT: PORT,
    FONTOP_NO_BROWSER: "1", // Electron 接管窗口，后端不抢系统浏览器
  };
  pyProc = spawn(PY_RUNTIME, ["-m", "src.server"], {
    cwd: PROJECT,
    env,
    stdio: ["ignore", "pipe", "pipe"],
  });
  pyProc.stdout.on("data", (d) => process.stdout.write(`[py] ${d}`));
  pyProc.stderr.on("data", (d) => process.stderr.write(`[py.err] ${d}`));
  pyProc.on("exit", (code) =>
    console.log(`[py] 后端退出 code=${code}`)
  );
}

function waitHealth(retries = 60, delay = 500) {
  return new Promise((resolve, reject) => {
    let n = 0;
    const tick = () => {
      http
        .get(`http://${HOST}:${PORT}/healthz`, (res) => {
          if (res.statusCode === 200) resolve(true);
          else retry();
        })
        .on("error", retry);
    };
    const retry = () => {
      if (n++ >= retries) reject(new Error("后端健康检查超时"));
      else setTimeout(tick, delay);
    };
    tick();
  });
}

function createWindow() {
  mainWin = new BrowserWindow({
    width: 1200,
    height: 800,
    webPreferences: {
      preload: path.join(__dirname, "preload.js"),
      contextIsolation: true,
      nodeIntegration: false,
    },
  });
  // 拦截外部链接，交给系统浏览器（截图页内不放外链，保险起见）
  mainWin.webContents.setWindowOpenHandler(({ url }) => {
    shell.openExternal(url);
    return { action: "deny" };
  });
  mainWin.loadURL(`http://${HOST}:${PORT}/`);
}

app.whenReady().then(async () => {
  startBackend();
  try {
    await waitHealth();
  } catch (e) {
    console.error(e.message);
  }
  createWindow();

  app.on("activate", () => {
    if (BrowserWindow.getAllWindows().length === 0) createWindow();
  });
});

app.on("window-all-closed", () => {
  if (pyProc) pyProc.kill();
  if (process.platform !== "darwin") app.quit();
});

app.on("before-quit", () => {
  if (pyProc) pyProc.kill("SIGTERM");
});
