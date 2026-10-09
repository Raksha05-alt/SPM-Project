import { Navigate, Route, Routes } from "react-router-dom";
import { AuthProvider } from "./auth/AuthProvider";
import { RequireRole } from "./auth/RequireRole";
import { useAuth } from "./auth/AuthContext";
import { Layout } from "./components/Layout";
import { CoordinatorQueue } from "./pages/CoordinatorQueue";
import { CoordinatorMyEvents } from "./pages/CoordinatorMyEvents";
import { CoordinatorEventDetail } from "./pages/CoordinatorEventDetail";
import { AttendeeEvents } from "./pages/AttendeeEvents";
import { EventRequestForm } from "./pages/EventRequestForm";
import { LoginPage } from "./pages/LoginPage";
import { OrganiserDashboard } from "./pages/OrganiserDashboard";
import { AccountPage } from "./pages/AccountPage";
import { MyRegistrations } from "./pages/MyRegistrations";
import { EquipmentAvailability } from "./pages/tech/EquipmentAvailability";
import { EquipmentRequests } from "./pages/tech/EquipmentRequests";
import { VenueBookingInbox } from "./pages/venue/VenueBookingInbox";
import { VenueCatalogue } from "./pages/venue/VenueCatalogue";
import { VenueDetail } from "./pages/venue/VenueDetail";

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
            path="/coordinator/mine"
            element={
              <RequireRole roles={["COORDINATOR"]}>
                <CoordinatorMyEvents />
              </RequireRole>
            }
          />
          <Route
            path="/coordinator/events/:id"
            element={
              <RequireRole roles={["COORDINATOR"]}>
                <CoordinatorEventDetail />
              </RequireRole>
            }
          />
          <Route
            path="/venues"
            element={
              <RequireRole roles={["VENUE_STAFF"]}>
                <VenueCatalogue />
              </RequireRole>
            }
          />
          <Route
            path="/venues/bookings"
            element={
              <RequireRole roles={["VENUE_STAFF"]}>
                <VenueBookingInbox />
              </RequireRole>
            }
          />
          <Route
            path="/venues/:id"
            element={
              <RequireRole roles={["VENUE_STAFF"]}>
                <VenueDetail />
              </RequireRole>
            }
          />
          <Route
            path="/equipment"
            element={
              <RequireRole roles={["TECH_SUPPORT"]}>
                <EquipmentRequests />
              </RequireRole>
            }
          />
          <Route
            path="/equipment/availability"
            element={
              <RequireRole roles={["TECH_SUPPORT"]}>
                <EquipmentAvailability />
              </RequireRole>
            }
          />
          <Route
            path="/events"
            element={
              <RequireRole roles={["ATTENDEE"]}>
                <AttendeeEvents />
              </RequireRole>
            }
          />
          <Route
            path="/events/mine"
            element={
              <RequireRole roles={["ATTENDEE"]}>
                <MyRegistrations />
              </RequireRole>
            }
          />
          <Route
            path="/account"
            element={
              <RequireRole>
                <AccountPage />
              </RequireRole>
            }
          />

          <Route path="*" element={<Navigate to="/" replace />} />
        </Routes>
      </Layout>
    </AuthProvider>
  );
}
