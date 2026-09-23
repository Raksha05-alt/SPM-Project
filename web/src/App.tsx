import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireRole } from "./auth/RequireRole";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { EventRequestForm } from "./pages/EventRequestForm";
import { LoginPage } from "./pages/LoginPage";
import { OrganiserDashboard } from "./pages/OrganiserDashboard";

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-8 text-slate-500">Loading…</p>;
  return <Navigate to={user ? "/organiser" : "/login"} replace />;
}

export default function App() {
  return (
    <AuthProvider>
      <Layout>
        <Routes>
          <Route path="/login" element={<LoginPage />} />
          <Route path="/" element={<Home />} />

          <Route
            path="/organiser"
            element={
              <RequireRole roles={["ORGANISER"]}>
                <OrganiserDashboard />
              </RequireRole>
            }
          />
          <Route
            path="/organiser/requests/new"
            element={
              <RequireRole roles={["ORGANISER"]}>
                <EventRequestForm />
              </RequireRole>
            }
          />
          <Route path="/organiser/requests/:id" element={
            <RequireRole roles={["ORGANISER"]}><EventRequestForm /></RequireRole>
          } />
          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </AuthProvider>
  );
}
