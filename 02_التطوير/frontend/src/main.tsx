import React from "react";
import ReactDOM from "react-dom/client";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import App from "./App";
import "./index.css";
import "./i18n";
import { ThemeProvider } from "./lib/theme";
import { LanguageProvider } from "./lib/language";
import { AuthGate } from "./components/AuthGate";

// QueryClient — يدير طلبات الـ API والتخزين المؤقت
const queryClient = new QueryClient({
  defaultOptions: {
    queries: {
      staleTime: 30_000,
      refetchOnWindowFocus: false,
      retry: 1,
    },
  },
});

ReactDOM.createRoot(document.getElementById("root")!).render(
  <React.StrictMode>
    <ThemeProvider>
      <LanguageProvider>
        <QueryClientProvider client={queryClient}>
          <AuthGate>
            <App />
          </AuthGate>
        </QueryClientProvider>
      </LanguageProvider>
    </ThemeProvider>
  </React.StrictMode>
);
