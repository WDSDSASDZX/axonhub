import { createFileRoute } from '@tanstack/react-router';
import PersonalHub from '@/features/personal';

export const Route = createFileRoute('/_authenticated/hub/')({ component: PersonalHub });
