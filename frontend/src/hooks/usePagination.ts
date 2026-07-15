import { useEffect, useMemo, useState } from "react";

import { USERS_PER_PAGE } from "@/lib/admin-shared";

type Pagination<T> = {
  page: number;
  setPage: React.Dispatch<React.SetStateAction<number>>;
  currentPage: number;
  totalPages: number;
  pageStart: number;
  pageItems: T[];
  rangeStart: number;
  rangeEnd: number;
  total: number;
};

export function usePagination<T>(
  items: T[],
  resetKey?: unknown,
  perPage: number = USERS_PER_PAGE,
): Pagination<T> {
  const [page, setPage] = useState(1);

  const totalPages = Math.max(1, Math.ceil(items.length / perPage));
  const currentPage = Math.min(page, totalPages);
  const pageStart = (currentPage - 1) * perPage;
  const pageItems = useMemo(
    () => items.slice(pageStart, pageStart + perPage),
    [items, pageStart, perPage],
  );

  useEffect(() => {
    setPage(1);
  }, [resetKey]);

  useEffect(() => {
    if (page > totalPages) setPage(totalPages);
  }, [page, totalPages]);

  return {
    page,
    setPage,
    currentPage,
    totalPages,
    pageStart,
    pageItems,
    rangeStart: pageItems.length ? pageStart + 1 : 0,
    rangeEnd: Math.min(pageStart + pageItems.length, items.length),
    total: items.length,
  };
}
