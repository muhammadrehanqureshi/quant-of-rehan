/**
 * The entry point. Strict mode is on in development: a double render is a
 * free chance to catch an effect that opens two streams or leaves a timer
 * behind, which is exactly the class of bug a live chart is prone to.
 */

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";

import { App } from "./App";
import { CustomChart } from "./examples/CustomChart";
import "./styles.css";

// A documented, reachable example: `/?example=1` renders the smallest chart
// with custom indicators, while the normal URL renders the full terminal.
const EXAMPLE = new URLSearchParams(window.location.search).get("example") === "1";

const container = document.getElementById("root");
if (container === null) {
  throw new Error("the page has no #root element to mount into");
}

createRoot(container).render(
  <StrictMode>
    {EXAMPLE ? <CustomChart /> : <App />}
  </StrictMode>,
);
