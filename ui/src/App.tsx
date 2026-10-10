import { lazy, Suspense } from "react";
import { MutationCache, QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { BrowserRouter, Link, NavLink, Route, Routes, useLocation } from "react-router-dom";
import { FilePlus2, Layers, Settings as SettingsIcon } from "lucide-react";
import { Toaster, toast } from "sonner";
import { ThemeProvider, useTheme } from "./lib/theme";
import { ThemeToggle } from "./components/ThemeToggle";
import { ErrorBoundary } from "./components/ErrorBoundary";
import { cn } from "./lib/utils";
import "./index.css";

const Dashboard = lazy(() => import("./pages/Dashboard"));
const NewRun = lazy(() => import("./pages/NewRun"));
const RunDetail = lazy(() => import("./pages/RunDetail"));
const Settings = lazy(() => import("./pages/Settings"));

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
  // Every failed mutation surfaces as a toast, unless the caller handles it
  mutationCache: new MutationCache({
    onError: (error, _v, _c, mutation) => {
      if (mutation.options.onError) return;
      toast.error(error instanceof Error ? error.message : String(error));
    },
  }),
});

const NAV = [
  { to: "/", label: "Runs", icon: Layers, end: true },
  { to: "/new", label: "New run", icon: FilePlus2, end: false },
  { to: "/settings", label: "Settings", icon: SettingsIcon, end: false },
];

function Mark() {
  return (
    <Link to="/" className="group flex items-center gap-2.5 px-2" aria-label="yomeru home">
      <span className="relative grid size-7 place-items-center overflow-hidden rounded-[var(--radius-sm)] bg-[hsl(var(--text))] text-[hsl(var(--bg))]">
        <span aria-hidden className="screentone absolute inset-0 opacity-40" />
        <span className="relative font-semibold leading-none">読</span>
      </span>
      <span className="text-[15px] font-semibold tracking-tight">yomeru</span>
    </Link>
  );
}

function Sidebar() {
  return (
    <aside className="sticky top-0 hidden h-dvh w-52 shrink-0 flex-col border-r border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-3 py-4 md:flex">
      <Mark />
      <nav className="mt-6 flex flex-col gap-0.5" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            className={({ isActive }) =>
              cn(
                "flex h-8 items-center gap-2.5 rounded-[var(--radius-sm)] px-2 text-sm transition-colors",
                isActive
                  ? "bg-[hsl(var(--bg-surface))] font-medium text-[hsl(var(--text))] shadow-[0_0_0_1px_hsl(var(--border))]"
                  : "text-[hsl(var(--text-body))] hover:bg-[hsl(var(--bg-subtle))] hover:text-[hsl(var(--text))]",
              )
            }
          >
            <Icon size={15} strokeWidth={1.75} />
            {label}
          </NavLink>
        ))}
      </nav>
      <div className="mt-auto flex items-center justify-between px-2">
        <span className="font-mono text-[11px] text-[hsl(var(--text-faint))]">v0.1</span>
        <ThemeToggle />
      </div>
    </aside>
  );
}

function MobileBar() {
  return (
    <header className="sticky top-0 z-20 flex items-center gap-3 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg))] px-4 py-2 md:hidden">
      <Mark />
      <nav className="ml-auto flex items-center gap-1" aria-label="Main">
        {NAV.map(({ to, label, icon: Icon, end }) => (
          <NavLink
            key={to}
            to={to}
            end={end}
            aria-label={label}
            className={({ isActive }) =>
              cn("grid size-8 place-items-center rounded-[var(--radius-sm)]",
                isActive ? "bg-[hsl(var(--bg-subtle))] text-[hsl(var(--text))]" : "text-[hsl(var(--text-muted))]")
            }
          >
            <Icon size={16} />
          </NavLink>
        ))}
      </nav>
    </header>
  );
}

function NotFound() {
  return (
    <div className="screentone-fade rounded-[var(--radius-md)] border border-[hsl(var(--border))] p-10">
      <p className="eyebrow">404</p>
      <h1 className="mt-2 text-2xl">Nothing on this page</h1>
      <Link to="/" className="mt-4 inline-block text-sm text-[hsl(var(--accent2))] underline underline-offset-4">
        Back to runs
      </Link>
    </div>
  );
}

function Layout() {
  const { pathname } = useLocation();
  const { resolved } = useTheme();
  return (
    <div className="flex min-h-screen bg-[hsl(var(--bg))]">
      <Sidebar />
      <div className="min-w-0 flex-1">
        <MobileBar />
        <main className="mx-auto max-w-[1400px] px-4 py-6 md:px-8 md:py-8">
          <ErrorBoundary resetKey={pathname}>
            <Suspense fallback={<p className="text-sm text-[hsl(var(--text-muted))]">loading…</p>}>
              <Routes>
                <Route path="/" element={<Dashboard />} />
                <Route path="/new" element={<NewRun />} />
                <Route path="/runs/:id" element={<RunDetail />} />
                <Route path="/settings" element={<Settings />} />
                <Route path="*" element={<NotFound />} />
              </Routes>
            </Suspense>
          </ErrorBoundary>
        </main>
      </div>
      <Toaster theme={resolved} position="bottom-right" toastOptions={{ className: "font-sans" }} />
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter basename="/ui">
          <Layout />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
