import { useEffect } from "react";

/** Sets the tab title to "<page> · DealFinder". */
export function useTitle(page: string): void {
  useEffect(() => {
    document.title = `${page} · DealFinder`;
  }, [page]);
}
