import { useQuery } from '@tanstack/react-query';

export const personalPaths = new Set([
  '/projects',
  '/users',
  '/roles',
  '/project/users',
  '/project/roles',
  '/data-storages',
  '/prompt-protection-rules',
  '/permission-demo',
]);

export function usePersonalProfile() {
  return useQuery({
    queryKey: ['personal-profile'],
    queryFn: async () => {
      const response = await fetch('/admin/system/profile');
      if (!response.ok) throw new Error('无法读取运行模式');
      return response.json() as Promise<{ personalMode: boolean }>;
    },
    staleTime: 60_000,
  });
}
