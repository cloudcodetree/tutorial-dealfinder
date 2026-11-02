import { useMemo } from "react";
import { marked } from "marked";
import { useTitle } from "../lib/useTitle";

/** One committed Markdown file, rendered. The file's first "# " line is the page's
 *  h1 and its title. The sources are files in this repo, never user input, so the
 *  HTML marked produces is trusted. */
export default function ContentPage({ source }: { source: string }) {
  const { title, html } = useMemo(() => {
    const [first, ...rest] = source.split("\n");
    const title = first.replace(/^#\s+/, "").trim();
    return { title, html: marked.parse(rest.join("\n"), { async: false }) as string };
  }, [source]);
  useTitle(title);
  return (
    <article className="content">
      <h1>{title}</h1>
      <div dangerouslySetInnerHTML={{ __html: html }} />
    </article>
  );
}
