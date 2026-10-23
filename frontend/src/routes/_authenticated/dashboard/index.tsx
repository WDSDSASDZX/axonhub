import { createFileRoute } from '@tanstack/react-router';
import { RouteGuard } from '@/components/route-guard';
import Dashboard from '@/features/dashboard';

export const Route = createFileRoute('/_authenticated/dashboard/')({
  component: () => (
    <RouteGuard requiredScopes={['read_dashboard']} scopeLevel='system'>
      <Dashboard />
    </RouteGuard>
  ),
});
