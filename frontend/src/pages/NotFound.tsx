import { Link } from "react-router-dom";
import { useTitle } from "../lib/useTitle";

export default function NotFound() {
  useTitle("Page not found");
  return (
    <>
      <h1>Page not found</h1>
      <p>There is no page at this address.</p>
      <p>
        <Link to="/">Back to Check a deal</Link>
      </p>
    </>
  );
}
