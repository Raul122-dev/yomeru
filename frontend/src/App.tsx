import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import {
  BrowserRouter,
  Link,
  Route,
  Routes,
  useLocation,
} from "react-router-dom";
import { ThemeProvider } from "./lib/theme";
import { ThemeToggle } from "./components/ThemeToggle";
import { cn } from "./lib/utils";
import Dashboard from "./pages/Dashboard";
import NewRun from "./pages/NewRun";
import RunDetail from "./pages/RunDetail";
import Settings from "./pages/Settings";
import "./index.css";

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, staleTime: 10_000 } },
});

function NavLink({ to, children }: { to: string; children: React.ReactNode }) {
  const { pathname } = useLocation();
  const active = pathname === to || (to !== "/" && pathname.startsWith(to));
  return (
    <Link
      to={to}
      className={cn(
        "text-sm transition-colors",
        active
          ? "font-medium text-[hsl(var(--text))]"
          : "text-[hsl(var(--text-muted))] hover:text-[hsl(var(--text))]",
      )}
    >
      {children}
    </Link>
  );
}

function Layout() {
  return (
    <div className="min-h-screen bg-[hsl(var(--bg))]">
      <header className="sticky top-0 z-10 border-b border-[hsl(var(--border))] bg-[hsl(var(--bg-surface))] bg-opacity-90 backdrop-blur">
        <div className="mx-auto flex max-w-7xl items-center gap-6 px-6 py-3">
          <Link
            to="/"
            className="text-base font-semibold text-[hsl(var(--accent))]"
          >
            yomeru
          </Link>
          <nav className="flex items-center gap-5">
            <NavLink to="/">runs</NavLink>
            <NavLink to="/new">new run</NavLink>
            <NavLink to="/settings">settings</NavLink>
          </nav>
          <div className="ml-auto">
            <ThemeToggle />
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-7xl px-6 py-8">
        <Routes>
          <Route path="/" element={<Dashboard />} />
          <Route path="/new" element={<NewRun />} />
          <Route path="/runs/:id" element={<RunDetail />} />
          <Route path="/settings" element={<Settings />} />
        </Routes>
      </main>
    </div>
  );
}

export default function App() {
  return (
    <ThemeProvider>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <Layout />
        </BrowserRouter>
      </QueryClientProvider>
    </ThemeProvider>
  );
}
