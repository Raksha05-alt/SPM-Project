import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireRole } from "./auth/RequireRole";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { CoordinatorQueue } from "./pages/CoordinatorQueue";
import { EventRequestForm } from "./pages/EventRequestForm";
import { LoginPage } from "./pages/LoginPage";
import { OrganiserDashboard } from "./pages/OrganiserDashboard";
import { PlaceholderPage } from "./pages/PlaceholderPage";

function Home() {
  const { user, loading } = useAuth();
  if (loading) return <p className="p-8 text-slate-500">Loading…</p>;
  return <Navigate to={user ? user.landing_path : "/login"} replace />;
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
          <Route
            path="/organiser/requests/:id"
            element={
              <RequireRole roles={["ORGANISER"]}>
                <EventRequestForm />
              </RequireRole>
            }
          />
          <Route
            path="/coordinator"
            element={
              <RequireRole roles={["COORDINATOR"]}>
                <CoordinatorQueue />
              </RequireRole>
            }
          />
          <Route
            path="/venues"
            element={
              <RequireRole roles={["VENUE_STAFF"]}>
                <PlaceholderPage title="Venues" sprint="sprint 2" />
              </RequireRole>
            }
          />
          <Route
            path="/equipment"
            element={
              <RequireRole roles={["TECH_SUPPORT"]}>
                <PlaceholderPage title="Equipment" sprint="sprint 4" />
              </RequireRole>
            }
          />
          <Route
            path="/events"
            element={
              <RequireRole roles={["ATTENDEE"]}>
                <PlaceholderPage title="Events open for registration" sprint="sprint 4" />
              </RequireRole>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </AuthProvider>
  );
}
