import { createFileRoute } from '@tanstack/react-router';
import { RouteGuard } from '@/components/route-guard';
import Dashboard from '@/features/dashboard';
import PersonalHub from '@/features/personal';
import { usePersonalProfile } from '@/features/personal/profile';

function ProtectedDashboard() {
  const { data: profile } = usePersonalProfile();
  if (profile?.personalMode) return <PersonalHub />;
  return (
    <RouteGuard requiredScopes={['read_dashboard']} scopeLevel='system'>
      <Dashboard />
    </RouteGuard>
  );
}

export const Route = createFileRoute('/_authenticated/')({
  component: ProtectedDashboard,
});
