import "./starter.css";
import "./app.css";

import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router-dom";
import { registerSW } from "virtual:pwa-register";
import { ConnectionAttr } from "./components/bits";
import { CookPage } from "./pages/CookPage";
import { Settings } from "./pages/Settings";
import { SlotPage } from "./pages/SlotPage";
import { Week } from "./pages/Week";
import { startSync } from "./sync";

const router = createBrowserRouter([
  { path: "/", element: <Week /> },
  { path: "/d/:date/:slot", element: <SlotPage /> },
  { path: "/c/:id", element: <CookPage /> },
  { path: "/settings", element: <Settings /> },
]);

registerSW({ immediate: true });
void startSync();

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ConnectionAttr />
    <RouterProvider router={router} />
  </StrictMode>,
);
