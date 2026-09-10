import type { CSSProperties } from "react";

// Workspace management dialogs belong to AgentMesh's light product surface.
// Keep their editable controls explicitly light so legacy/global dark input
// rules cannot turn a single modal into a black form inside the light shell.
export const lightDialogControlStyle: CSSProperties = {
  backgroundColor: "#ffffff",
  color: "#24312e",
  borderColor: "#d6e0dc",
  boxShadow: "none",
  caretColor: "#3f776b",
  colorScheme: "light",
};
