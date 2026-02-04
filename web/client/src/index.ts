import { createElement } from "react";
import { createRoot } from "react-dom/client";
import App from "./App";
import "./index.css";

const container = document.getElementById("root");
if (!container) {
  throw new Error("Missing root element");
}

const root = createRoot(container);
root.render(createElement(App));
