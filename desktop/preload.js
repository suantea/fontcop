// 预加载脚本：仅暴露最小化接口给渲染进程（当前 web/app.js 走 fetch 同源，
// 无需额外桥接；保留 contextIsolation 安全边界）。
const { contextBridge } = require("electron");

contextBridge.exposeInMainWorld("fontcop", {
  version: "1.1.0",
  isDesktop: true,
});
