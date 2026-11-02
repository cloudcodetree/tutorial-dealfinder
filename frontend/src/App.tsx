import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CheckPage from "./pages/CheckPage";
import ContentPage from "./pages/ContentPage";
import NotFound from "./pages/NotFound";
import howWeRank from "./content/how-we-rank.md?raw";
import privacy from "./content/privacy.md?raw";

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<CheckPage />} />
          <Route path="/check" element={<CheckPage />} />
          <Route path="/how-we-rank" element={<ContentPage source={howWeRank} />} />
          <Route path="/privacy" element={<ContentPage source={privacy} />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
