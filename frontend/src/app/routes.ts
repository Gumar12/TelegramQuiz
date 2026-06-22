import {
  Bot,
  LayoutDashboard,
  ListChecks,
  PencilLine,
  Play,
  PlusSquare,
  Settings,
  UsersRound,
  type LucideIcon,
} from 'lucide-react';

export type AppRouteId =
  | 'dashboard'
  | 'create'
  | 'editor'
  | 'quizzes'
  | 'runs'
  | 'accounts'
  | 'settings';

export type AppRoute = {
  id: AppRouteId;
  label: string;
  title: string;
  description: string;
  icon: LucideIcon;
};

export const appRoutes: AppRoute[] = [
  {
    id: 'dashboard',
    label: 'Главная',
    title: 'Главная',
    description: 'Рабочее состояние, быстрые действия и очередь запусков.',
    icon: LayoutDashboard,
  },
  {
    id: 'create',
    label: 'Создание',
    title: 'Создание',
    description: 'Импорт DOCX/JSON и подготовка новых квизов.',
    icon: PlusSquare,
  },
  {
    id: 'editor',
    label: 'Редактор',
    title: 'Редактор',
    description: 'Правка вопросов, вариантов, контекстов и ошибок в JSON.',
    icon: PencilLine,
  },
  {
    id: 'quizzes',
    label: 'Квизы',
    title: 'Квизы',
    description: 'Готовые и черновые квизы, статусы проверки и запуска.',
    icon: ListChecks,
  },
  {
    id: 'runs',
    label: 'Запуски',
    title: 'Запуски',
    description: 'Активные и завершенные загрузки в Telegram QuizBot.',
    icon: Play,
  },
  {
    id: 'accounts',
    label: 'Аккаунты',
    title: 'Аккаунты',
    description: 'Публичные профили Telegram без секретов и session contents.',
    icon: UsersRound,
  },
  {
    id: 'settings',
    label: 'Настройки',
    title: 'Настройки',
    description: 'Workspace, модель и безопасные значения по умолчанию.',
    icon: Settings,
  },
];

export const brandIcon = Bot;

export function getRoute(routeId: AppRouteId): AppRoute {
  return appRoutes.find((route) => route.id === routeId) ?? appRoutes[0];
}
