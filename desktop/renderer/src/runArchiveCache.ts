import type { RunSummary } from "./types";

export type RunListScope = "active" | "archived";

export interface RunSummaryScopes {
  active: RunSummary[];
  archived: RunSummary[];
}

export type RunSummaryCache = Record<string, RunSummaryScopes>;

const emptyScopes = (): RunSummaryScopes => ({ active: [], archived: [] });

const sortRuns = (runs: RunSummary[]): RunSummary[] => (
  [...runs].sort((left, right) => right.created_at.localeCompare(left.created_at))
);

const freshness = (run: RunSummary): string => (
  run.updated_at || run.archived_at || run.checked_at || run.created_at
);

const preferFreshSummary = (listed: RunSummary | undefined, authoritative: RunSummary): RunSummary => {
  if (!listed) return authoritative;
  return freshness(listed) > freshness(authoritative) ? listed : authoritative;
};

export function applyArchivedRun(
  cache: RunSummaryCache,
  projectName: string,
  summary: RunSummary,
): RunSummaryCache {
  const current = cache[projectName] || emptyScopes();
  const listed = current.archived.find((run) => run.id === summary.id);
  const archived = preferFreshSummary(listed, summary);
  return {
    ...cache,
    [projectName]: {
      active: current.active.filter((run) => run.id !== summary.id),
      archived: sortRuns([
        archived,
        ...current.archived.filter((run) => run.id !== summary.id),
      ]),
    },
  };
}

export function applyRunSummary(
  cache: RunSummaryCache,
  projectName: string,
  scope: RunListScope,
  summary: RunSummary,
): RunSummaryCache {
  if (scope === "archived") return applyArchivedRun(cache, projectName, summary);
  const current = cache[projectName] || emptyScopes();
  return {
    ...cache,
    [projectName]: {
      ...current,
      active: sortRuns([
        summary,
        ...current.active.filter((run) => run.id !== summary.id),
      ]),
    },
  };
}

export function reconcileRunScope(
  cache: RunSummaryCache,
  projectName: string,
  scope: RunListScope,
  listedRuns: RunSummary[],
  authoritativeArchives: RunSummary[],
): RunSummaryCache {
  const current = cache[projectName] || emptyScopes();
  const archivedIds = new Set(authoritativeArchives.map((run) => run.id));
  let reconciled = scope === "active"
    ? listedRuns.filter((run) => !archivedIds.has(run.id))
    : [...listedRuns];

  if (scope === "archived") {
    for (const authoritative of authoritativeArchives) {
      const listed = reconciled.find((run) => run.id === authoritative.id);
      const preferred = preferFreshSummary(listed, authoritative);
      reconciled = [preferred, ...reconciled.filter((run) => run.id !== authoritative.id)];
    }
  }

  return {
    ...cache,
    [projectName]: {
      ...current,
      [scope]: sortRuns(reconciled),
    },
  };
}
