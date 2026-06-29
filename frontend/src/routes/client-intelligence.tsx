import { createFileRoute, useRouter } from "@tanstack/react-router";
import { ArrowLeft } from "lucide-react";

export const Route = createFileRoute("/client-intelligence")({ component: ClientIntelPage });

function ClientIntelPage() {
  const router = useRouter();

  return (
    <div className="flex min-h-[60vh] items-center justify-center px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold text-foreground">Coming soon</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Client Intelligence is under development and will be available in a future release.
        </p>
        <button
          type="button"
          onClick={() => router.history.back()}
          className="mt-6 inline-flex items-center gap-2 rounded-md border border-border bg-card px-4 py-2 text-sm font-medium text-foreground transition-colors hover:bg-elevated"
        >
          <ArrowLeft className="h-4 w-4" />
          Back
        </button>
      </div>
    </div>
  );
}
