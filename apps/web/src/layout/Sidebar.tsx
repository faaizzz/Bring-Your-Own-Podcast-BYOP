import { NavLink } from 'react-router-dom';

import { menu } from './menu';

type SidebarProps = {
  /** Desktop: collapsed to an icon rail. Mobile: slid open over the page. */
  collapsed: boolean;
  isMobile: boolean;
  onNavigate: () => void;
};

export function Sidebar({ collapsed, isMobile, onNavigate }: SidebarProps): React.JSX.Element {
  const stateClass = collapsed ? (isMobile ? 'mob-open' : 'navbar-collapsed') : '';

  return (
    <nav className={`pcoded-navbar menu-light menupos-fixed ${stateClass}`} aria-label="Main">
      <div className="navbar-wrapper">
        <div className="navbar-content next-scroll" style={{ overflowY: 'auto' }}>
          <ul className="nav pcoded-inner-navbar">
            {menu.map((group) => (
              <GroupItems key={group.id} group={group} onNavigate={onNavigate} />
            ))}
          </ul>
        </div>
      </div>
    </nav>
  );
}

function GroupItems({
  group,
  onNavigate,
}: {
  group: (typeof menu)[number];
  onNavigate: () => void;
}): React.JSX.Element {
  return (
    <>
      <li className="nav-item pcoded-menu-caption">
        <label className="text-capitalize">{group.title}</label>
      </li>
      {group.items.map(({ id, title, url, icon: Icon }) => (
        <li key={id} className="nav-item">
          <NavLink to={url} end={url === '/'} className="nav-link" onClick={onNavigate}>
            <span className="pcoded-micon">
              <Icon aria-hidden="true" />
            </span>
            <span className="pcoded-mtext">{title}</span>
          </NavLink>
        </li>
      ))}
    </>
  );
}
