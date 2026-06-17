import { startDashboard } from "./js/app.js";

startDashboard().catch((error) => {
    console.error("Dashboard bootstrap failed:", error);
});
