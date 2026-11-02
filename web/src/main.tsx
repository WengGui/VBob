/**
 * 前端入口：挂载 React 根节点并加载全局样式。
 * StrictMode 仅在开发环境启用，用于提前暴露副作用问题。
 */
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
