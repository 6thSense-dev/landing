import { createContext, useContext } from "react";
export const WorkspacePreviewContext = createContext(null);
export const useWorkspacePreview = () => useContext(WorkspacePreviewContext);
