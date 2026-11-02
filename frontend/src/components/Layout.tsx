import { Link, NavLink, Outlet } from "react-router-dom";

export const FOOTER_NOTE =
  "Verdicts come from a price model trained on a fixed July 2026 snapshot, so its fair prices may be out of date. " +
  "Check the store before you buy. Any AI-written text here is labeled AI-written.";

export default function Layout() {
  return (
    <>
      <a className="skip-link" href="#main">
        Skip to content
      </a>
      <header className="site-header">
        <Link to="/" className="brand">
          DealFinder<span aria-hidden="true">.</span>
        </Link>
        <nav aria-label="Main">
          <NavLink to="/check">Check a deal</NavLink>
          <NavLink to="/how-we-rank">How we rank</NavLink>
        </nav>
      </header>
      <main id="main" tabIndex={-1}>
        <Outlet />
      </main>
      <footer className="site-footer">
        <nav aria-label="About DealFinder">
          <Link to="/how-we-rank">How we rank</Link>
          <Link to="/privacy">Privacy</Link>
          {/* The lab is a separate page the backend serves, so this is a full page load. */}
          <a href="/lab">Under the hood</a>
        </nav>
        <p>{FOOTER_NOTE}</p>
      </footer>
    </>
  );
}
