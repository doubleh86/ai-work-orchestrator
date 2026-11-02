import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import React from "react";
import ReactDOM from "react-dom/client";

import { App } from "./App";
import "./styles/tokens.css";
import "./styles/app.css";
import "./styles/redesign.css";
import "./styles/execution-monitor.css";
import "./styles/work-centered.css";
import "./styles/chat-first.css";
import "./styles/chat-markdown.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <App />
  </React.StrictMode>,
);
