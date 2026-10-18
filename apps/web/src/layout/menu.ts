import type { IconType } from 'react-icons';
import { FiClock, FiDollarSign, FiHome, FiKey, FiMic } from 'react-icons/fi';

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
    ],
  },
];

export const menuItems: MenuItem[] = menu.flatMap((group) => group.items);

export function findMenuItem(pathname: string): MenuItem | undefined {
  const normalised = pathname.length > 1 ? pathname.replace(/\/+$/, '') : pathname;
  return menuItems.find((item) => item.url === normalised);
}
