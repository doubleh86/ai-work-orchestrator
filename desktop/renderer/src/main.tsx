import "@fontsource-variable/geist";
import "@fontsource-variable/jetbrains-mono";
import React from "react";
import ReactDOM from "react-dom/client";

import { MakerApp } from "./MakerApp";
import "./styles/tokens.css";
import "./styles/maker-controls.css";
import "./styles/maker.css";

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <MakerApp />
  </React.StrictMode>,
);
