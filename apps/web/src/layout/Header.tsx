import { useState } from 'react';
import { Dropdown } from 'react-bootstrap';
import { FiLogOut, FiMoon, FiMoreVertical, FiSun, FiUser } from 'react-icons/fi';
import { useNavigate } from 'react-router-dom';

import { useMe, useLogout } from '../lib/auth';
import { useColorMode } from '../lib/colorMode';
import { Brand } from './Brand';

type HeaderProps = {
  menuToggled: boolean;
  /** Whether the sidebar is currently visible, for assistive tech. */
  menuExpanded: boolean;
  onToggleMenu: () => void;
};

export function Header({
  menuToggled,
  menuExpanded,
  onToggleMenu,
}: HeaderProps): React.JSX.Element {
  const [moreOpen, setMoreOpen] = useState(false);
  const { mode, toggle } = useColorMode();
  const { data: user } = useMe();
  const logout = useLogout();
  const navigate = useNavigate();

  const signOut = () => {
    logout.mutate(undefined, {
      onSettled: () => {
        navigate('/login', { replace: true });
      },
    });
  };

  return (
    <header
      className="navbar pcoded-header navbar-expand-lg header-blue headerpos-fixed"
      style={{ zIndex: 1009 }}
    >
      <div className="m-header">
        <button
          type="button"
          id="mobile-collapse"
          className={`mobile-menu ${menuToggled ? 'on' : ''}`}
          aria-label="Toggle navigation"
          aria-expanded={menuExpanded}
          onClick={onToggleMenu}
        >
          <span />
        </button>
        <Brand />
        <button
          type="button"
          className={`mob-toggler ${moreOpen ? 'on' : ''}`}
          aria-label="Toggle header menu"
          aria-expanded={moreOpen}
          onClick={() => setMoreOpen((open) => !open)}
        >
          <FiMoreVertical aria-hidden="true" />
        </button>
      </div>
      <div
        className={`collapse navbar-collapse ${moreOpen ? 'd-block' : ''}`}
        style={{ justifyContent: 'end' }}
      >
        <ul className="navbar-nav ms-auto align-items-center">
          <li className="nav-item">
            <button
              type="button"
              className="btn-theme-toggle"
              onClick={toggle}
              aria-label={mode === 'dark' ? 'Switch to light mode' : 'Switch to dark mode'}
              title={mode === 'dark' ? 'Light mode' : 'Dark mode'}
            >
              {mode === 'dark' ? <FiSun aria-hidden="true" /> : <FiMoon aria-hidden="true" />}
            </button>
          </li>
          <li className="nav-item">
            <Dropdown align="end" className="drp-user">
              <Dropdown.Toggle as="button" className="btn-user" aria-label="Account menu">
                <FiUser aria-hidden="true" />
              </Dropdown.Toggle>
              <Dropdown.Menu align="end" className="profile-notification">
                <div className="pro-head">
                  <span>{user?.email ?? 'Account'}</span>
                </div>
                <Dropdown.Item as="button" onClick={signOut}>
                  <FiLogOut aria-hidden="true" /> Sign out
                </Dropdown.Item>
              </Dropdown.Menu>
            </Dropdown>
          </li>
        </ul>
      </div>
    </header>
  );
}
