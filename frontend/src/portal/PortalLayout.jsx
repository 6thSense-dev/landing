import { Outlet } from "react-router-dom";
import { SessionProvider } from "./useSession.jsx";

export default function PortalLayout() {
  return (
    <SessionProvider>
      <Outlet />
    </SessionProvider>
  );
}
