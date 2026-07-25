import React from "react";
import { createRoot } from "react-dom/client";
import { CssBaseline, ThemeProvider, createTheme } from "@mui/material";
import App from "./App";
import "./styles.css";

const theme = createTheme({
  palette: {
    mode: "dark",
    primary: { main: "#e6b85c" },
    secondary: { main: "#b24636" },
    background: { default: "#080705", paper: "#15120e" },
    text: { primary: "#f3e8cc", secondary: "#aa9c7e" }
  },
  typography: {
    fontFamily: '"IBM Plex Sans", "Segoe UI", sans-serif',
    h1: { fontFamily: '"Bodoni 72", Georgia, serif', letterSpacing: "0.04em" },
    h2: { fontFamily: '"Bodoni 72", Georgia, serif' }
  },
  shape: { borderRadius: 2 }
});

createRoot(document.getElementById("root")).render(
  <React.StrictMode>
    <ThemeProvider theme={theme}>
      <CssBaseline />
      <App />
    </ThemeProvider>
  </React.StrictMode>
);
