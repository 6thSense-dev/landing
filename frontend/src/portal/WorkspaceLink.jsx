import { Link } from "react-router-dom";
import { useSession } from "./useSession.jsx";
import { useWorkspacePreview } from "./WorkspaceContext.jsx";
export default function WorkspaceLink({ className = "cat-topbar__logout" }) {
  const { user } = useSession();
  const preview = useWorkspacePreview();
  return user?.workspace_enabled === true && !preview ? <Link className={className} to="/portal/workspace">Workspace</Link> : null;
}
