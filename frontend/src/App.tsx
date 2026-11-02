import { BrowserRouter, Route, Routes } from "react-router-dom";
import Layout from "./components/Layout";
import NotFound from "./pages/NotFound";
import { useTitle } from "./lib/useTitle";

// Placeholder pages. Check a deal (Task 5) and the content pages (Task 7) replace them.
function Placeholder({ title }: { title: string }) {
  useTitle(title);
  return <h1>{title}</h1>;
}

export default function App() {
  return (
    <BrowserRouter>
      <Routes>
        <Route element={<Layout />}>
          <Route path="/" element={<Placeholder title="Check a deal" />} />
          <Route path="/check" element={<Placeholder title="Check a deal" />} />
          <Route path="/how-we-rank" element={<Placeholder title="How we rank" />} />
          <Route path="/privacy" element={<Placeholder title="Privacy" />} />
          <Route path="*" element={<NotFound />} />
        </Route>
      </Routes>
    </BrowserRouter>
  );
}
