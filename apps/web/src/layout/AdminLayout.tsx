import { useState } from 'react';
import { Outlet } from 'react-router-dom';

import { useMediaQuery } from '../lib/useMediaQuery';
import { Breadcrumb } from './Breadcrumb';
import { Header } from './Header';
import { Sidebar } from './Sidebar';
import { ToastProvider } from './ToastProvider';

const MOBILE_QUERY = '(max-width: 991.98px)';

export function AdminLayout(): React.JSX.Element {
  const isMobile = useMediaQuery(MOBILE_QUERY);
  // Desktop: the sidebar is expanded and can collapse to an icon rail.
  // Mobile: the sidebar is hidden and slides in over the page.
  const [railCollapsed, setRailCollapsed] = useState(false);
  const [mobileOpen, setMobileOpen] = useState(false);

  const menuToggled = isMobile ? mobileOpen : railCollapsed;
  const toggleMenu = () => {
    if (isMobile) setMobileOpen((open) => !open);
    else setRailCollapsed((collapsed) => !collapsed);
  };
  const closeMobileMenu = () => {
    setMobileOpen(false);
  };

  const chrome = (
    <>
      <Sidebar collapsed={menuToggled} isMobile={isMobile} onNavigate={closeMobileMenu} />
      <Header
        menuToggled={menuToggled}
        menuExpanded={isMobile ? mobileOpen : !railCollapsed}
        onToggleMenu={toggleMenu}
      />
    </>
  );

  return (
    <ToastProvider>
      {isMobile ? (
        <div className={`nav-outside mob-fixed ${mobileOpen ? 'mob-backdrop' : ''}`}>{chrome}</div>
      ) : (
        chrome
      )}
      <main className="pcoded-main-container" onClick={closeMobileMenu}>
        <div className="pcoded-wrapper">
          <div className="pcoded-content">
            <div className="pcoded-inner-content">
              <Breadcrumb />
              <Outlet />
            </div>
          </div>
        </div>
      </main>
    </ToastProvider>
  );
}
