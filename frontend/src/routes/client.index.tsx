import { createFileRoute, Link } from "@tanstack/react-router";
import { useQuery } from "@tanstack/react-query";

import { Card, SectionHeader } from "@/components/bsg/widgets";
import { PageLoadingScreen } from "@/components/bsg/PageLoadingScreen";
import { summarizeClientPortfolio } from "@/features/client-dashboard/client-dashboard-utils";
import { clientCommunicationsListQueryOptions } from "@/features/client-reports/useClientReportsQueries";
import { formatReportDate } from "@/features/reports/report-utils";
import { typeLabel } from "@/features/reports/report-status";
import { getTrafficLightLabel } from "@/lib/delivery-traffic-light";
import { deliveryPortfolioQueryOptions } from "@/lib/queries/delivery";
import { useAuthStore } from "@/stores/useAuthStore";

export const Route = createFileRoute("/client/")({ component: ClientHome });

function ClientHome() {
  const reportsQuery = useQuery(clientCommunicationsListQueryOptions(5, 0));
  const portfolioQuery = useQuery(deliveryPortfolioQueryOptions);
  const user = useAuthStore((state) => state.user);
  const reports = reportsQuery.data?.data ?? [];
  const portfolio = summarizeClientPortfolio(portfolioQuery.data);
  const welcomeName = user?.full_name?.trim().split(/\s+/)[0];
  const confidenceTone =
    portfolio.confidence === null
      ? "text-muted-foreground"
      : portfolio.confidence >= 85
        ? "text-[color:var(--success)]"
        : portfolio.confidence >= 70
          ? "text-[color:var(--warning)]"
          : "text-[color:var(--danger)]";

  if (
    (portfolioQuery.isLoading || reportsQuery.isLoading) &&
    !portfolioQuery.isError &&
    !reportsQuery.isError
  ) {
    return <PageLoadingScreen />;
  }

  return (
    <div className="space-y-5">
      <Card>
        <SectionHeader
          title={welcomeName ? `Welcome, ${welcomeName}` : "Welcome"}
          sub="Your delivery snapshot"
        />
        <div className="grid grid-cols-1 gap-4 md:grid-cols-3">
          <Link
            to="/client/status"
            className="rounded-md border border-[color:var(--brand)]/30 bg-[color:var(--brand)]/5 p-6 transition hover:ring-1 hover:ring-[color:var(--brand)] md:col-span-1"
          >
            <div className="text-xs uppercase tracking-wider text-muted-foreground">
              Delivery Confidence
            </div>
            {portfolioQuery.isError ? (
              <div className="mt-3 text-sm text-[color:var(--danger)]">Unavailable</div>
            ) : (
              <div className={`mt-2 text-5xl font-semibold ${confidenceTone}`}>
                {portfolio.confidence === null ? "—" : `${portfolio.confidence}%`}
              </div>
            )}
            <div className="mt-1 text-xs text-muted-foreground">
              Open Delivery Status for details
            </div>
          </Link>

          <div className="md:col-span-2">
            <div className="mb-3 text-[10px] font-semibold uppercase tracking-wider text-muted-foreground">
              Your projects
            </div>
            {portfolioQuery.isError ? (
              <p className="text-xs text-[color:var(--danger)]" role="alert">
                Failed to load your delivery snapshot.{" "}
                <button
                  type="button"
                  className="underline"
                  onClick={() => void portfolioQuery.refetch()}
                >
                  Retry
                </button>
              </p>
            ) : portfolio.projects.length === 0 ? (
              <p className="text-xs text-muted-foreground">
                No projects are assigned to your account yet.
              </p>
            ) : (
              <div>
                <p className="text-xs text-muted-foreground">
                  {portfolio.totalProjects} {portfolio.totalProjects === 1 ? "project" : "projects"}
                  {" · "}
                  {portfolio.onTrackProjects} on track · {portfolio.atRiskProjects} need attention
                  {portfolio.waitingForDataProjects > 0
                    ? ` · ${portfolio.waitingForDataProjects} waiting for data`
                    : ""}
                </p>
                <ul className="mt-3 grid grid-cols-1 gap-2 sm:grid-cols-2">
                  {portfolio.projects.slice(0, 4).map((project) => (
                    <li
                      key={project.id}
                      className="flex items-center justify-between rounded border border-border px-3 py-2 text-xs"
                    >
                      <span className="truncate font-medium">{project.name}</span>
                      <span className="ml-3 shrink-0 text-muted-foreground">
                        {project.confidence === null
                          ? "No data"
                          : `${getTrafficLightLabel(project.trafficLight)} · ${project.confidence}%`}
                      </span>
                    </li>
                  ))}
                </ul>
                {portfolio.hasMoreProjects || portfolio.projects.length > 4 ? (
                  <Link
                    to="/client/status"
                    className="mt-2 inline-block text-[11px] text-[color:var(--brand)] hover:underline"
                  >
                    View all projects
                  </Link>
                ) : null}
              </div>
            )}
          </div>
        </div>
      </Card>

      <div className="grid grid-cols-1 gap-5 lg:grid-cols-2">
        <Card>
          <SectionHeader
            title="Latest Updates"
            sub="Sent reports from your delivery team"
            right={
              <Link
                to="/client/reports"
                className="text-[11px] font-medium text-[color:var(--brand)] hover:underline"
              >
                View all
              </Link>
            }
          />
          {reportsQuery.isError ? (
            <p className="text-xs text-[color:var(--danger)]" role="alert">
              Failed to load reports.{" "}
              <button
                type="button"
                className="underline"
                onClick={() => void reportsQuery.refetch()}
              >
                Retry
              </button>
            </p>
          ) : reports.length === 0 ? (
            <p className="text-xs text-muted-foreground">
              No sent reports yet. When your delivery team sends a report, it will show up here.
            </p>
          ) : (
            <ul className="space-y-2 text-xs">
              {reports.map((report) => (
                <li key={report.id}>
                  <Link
                    to="/client/reports"
                    className="block rounded border border-border bg-elevated px-3 py-2 hover:ring-1 hover:ring-[color:var(--brand)]"
                  >
                    <div className="font-medium">{report.subject}</div>
                    <div className="text-[10px] text-muted-foreground">
                      {report.project_name} · {typeLabel(report.comm_type)} ·{" "}
                      {formatReportDate(report.sent_at ?? report.updated_at)}
                    </div>
                  </Link>
                </li>
              ))}
            </ul>
          )}
        </Card>

        <Card>
          <SectionHeader title="Have a question?" sub="Use Ask Agent for project questions" />
          <p className="text-xs text-muted-foreground">
            For delivery questions, open{" "}
            <Link to="/client/ask" className="text-foreground underline">
              Ask Agent
            </Link>
            .
          </p>
        </Card>
      </div>
    </div>
  );
}
