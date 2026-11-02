import * as Sentry from "@sentry/react";

// Error reports to Sentry, only when the build sets VITE_SENTRY_DSN. A report never
// carries what the shopper typed: query strings come off every URL, and the
// Referer header (the full page URL) is dropped.

const strip = (url?: string) => (url ? url.split("?")[0].split("#")[0] : url);

export function initSentry(): void {
  const dsn = import.meta.env.VITE_SENTRY_DSN;
  if (!dsn) return;
  Sentry.init({
    dsn,
    // Sentry 11 replaced sendDefaultPii with per-category switches. All of them are off:
    // no user fields, cookies, headers, bodies or query parameters.
    dataCollection: { userInfo: false, cookies: false, httpHeaders: false, httpBodies: [], urlQueryParams: false },
    environment: import.meta.env.MODE,
    beforeSend(event) {
      if (event.request) {
        event.request.url = strip(event.request.url);
        delete event.request.query_string;
        delete event.request.cookies;
        if (event.request.headers) {
          for (const name of Object.keys(event.request.headers))
            if (name.toLowerCase() === "referer") delete event.request.headers[name];
        }
      }
      return event;
    },
    beforeBreadcrumb(crumb) {
      if (crumb.data) {
        for (const key of ["url", "from", "to"])
          if (typeof crumb.data[key] === "string") crumb.data[key] = strip(crumb.data[key]);
      }
      return crumb;
    },
  });
}
