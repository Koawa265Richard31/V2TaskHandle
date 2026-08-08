// preload:向渲染进程注入 API 基地址(指向本地后端)和后端状态接口
const { contextBridge, ipcRenderer } = require("electron");

contextBridge.exposeInMainWorld("__API_BASE__", "http://127.0.0.1:8000");

contextBridge.exposeInMainWorld("backend", {
  status: () => ipcRenderer.invoke("backend:status"),
  switchRole: (role) => ipcRenderer.invoke("backend:switch-role", role),
  logs: () => ipcRenderer.invoke("backend:logs"),
  onStatus: (cb) => {
    ipcRenderer.on("backend:status-changed", (_e, data) => cb(data));
  },
});
