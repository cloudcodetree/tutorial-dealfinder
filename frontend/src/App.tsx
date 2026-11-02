import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import CheckPage from "./pages/CheckPage";
import NotFound from "./pages/NotFound";
import { useTitle } from "./lib/useTitle";

// Placeholder pages until the content pages (Task 7) replace them.
function Placeholder({ title }: { title: string }) {
  useTitle(title);
  return <h1>{title}</h1>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<CheckPage />} />
          <Route path="/check" element={<CheckPage />} />
          <Route path="/how-we-rank" element={<Placeholder title="How we rank" />} />
          <Route path="/privacy" element={<Placeholder title="Privacy" />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
