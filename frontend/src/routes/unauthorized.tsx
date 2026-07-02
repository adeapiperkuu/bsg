import { createFileRoute, Link } from "@tanstack/react-router";

export const Route = createFileRoute("/unauthorized")({
  component: UnauthorizedPage,
});

function UnauthorizedPage() {
  return (
    <div className="flex min-h-screen items-center justify-center bg-background px-4">
      <div className="max-w-md text-center">
        <h1 className="text-xl font-semibold text-foreground">Access denied</h1>
        <p className="mt-2 text-sm text-muted-foreground">
          Your account does not have permission to view this page.
        </p>
        <Link to="/login" className="mt-6 inline-block text-sm text-primary hover:underline">
          Return to sign in
        </Link>
      </div>
    </div>
  );
}
