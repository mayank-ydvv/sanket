import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import { createBrowserRouter, RouterProvider } from "react-router";
import { AuthProvider } from "@/lib/auth";
import { ThemeProvider } from "@/lib/theme";
import Alerts from "@/pages/app/Alerts";
import AppLayout from "@/pages/app/AppLayout";
import BenchmarkPage from "@/pages/app/Benchmark";
import Incidents from "@/pages/app/Incidents";
import Overview from "@/pages/app/Overview";
import AuthPage from "@/pages/AuthPage";
import Landing from "@/pages/Landing";
import "./index.css";

const router = createBrowserRouter([
  { path: "/", element: <Landing /> },
  { path: "/login", element: <AuthPage mode="login" /> },
  { path: "/signup", element: <AuthPage mode="signup" /> },
  {
    path: "/app",
    element: <AppLayout />,
    children: [
      { index: true, element: <Overview /> },
      { path: "incidents", element: <Incidents /> },
      { path: "alerts", element: <Alerts /> },
      { path: "benchmark", element: <BenchmarkPage /> },
    ],
  },
]);

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <ThemeProvider>
      <AuthProvider>
        <RouterProvider router={router} />
      </AuthProvider>
    </ThemeProvider>
  </StrictMode>,
);
