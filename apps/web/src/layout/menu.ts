import type { IconType } from 'react-icons';
import {
  FiClock,
  FiDollarSign,
  FiEdit3,
  FiHome,
  FiKey,
  FiMic,
  FiTag,
  FiUsers,
} from 'react-icons/fi';

export type MenuItem = {
  id: string;
  title: string;
  url: string;
  icon: IconType;
  /** Extra breadcrumb segment shown before the title, e.g. "Settings". */
  parentTitle?: string;
};

export type MenuGroup = {
  id: string;
  title: string;
  items: MenuItem[];
};

export const menu: MenuGroup[] = [
  {
    id: 'navigation',
    title: 'Navigation',
    items: [
      { id: 'dashboard', title: 'Dashboard', url: '/', icon: FiHome },
      { id: 'shows', title: 'Shows', url: '/shows', icon: FiMic },
      { id: 'history', title: 'History', url: '/history', icon: FiClock },
      { id: 'costs', title: 'Costs', url: '/costs', icon: FiDollarSign },
    ],
  },
  {
    id: 'settings',
    title: 'Settings',
    items: [
      {
        id: 'integrations',
        title: 'Integrations',
        url: '/settings/integrations',
        icon: FiKey,
        parentTitle: 'Settings',
      },
      {
        id: 'styles',
        title: 'Styles',
        url: '/settings/styles',
        icon: FiEdit3,
        parentTitle: 'Settings',
      },
      {
        id: 'personas',
        title: 'Personas',
        url: '/settings/personas',
        icon: FiUsers,
        parentTitle: 'Settings',
      },
      {
        id: 'pricing',
        title: 'Pricing',
        url: '/settings/pricing',
        icon: FiTag,
        parentTitle: 'Settings',
      },
    ],
  },
];

export const menuItems: MenuItem[] = menu.flatMap((group) => group.items);

export function findMenuItem(pathname: string): MenuItem | undefined {
  const normalised = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  const exact = menuItems.find((item) => item.url === normalised);
  if (exact) return exact;
  // Child pages (/shows/new, /shows/:id) belong to their section.
  return menuItems.find((item) => item.url !== '/' && normalised.startsWith(`${item.url}/`));
}
