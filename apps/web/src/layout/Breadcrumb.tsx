import { useEffect } from 'react';
import { FiHome } from 'react-icons/fi';
import { Link, useLocation } from 'react-router-dom';

import { findMenuItem } from './menu';

export function Breadcrumb(): React.JSX.Element | null {
  const { pathname } = useLocation();
  const item = findMenuItem(pathname);

  useEffect(() => {
    document.title = item ? `${item.title} | BYOP` : 'BYOP';
  }, [item]);

  if (!item) return null;

  return (
    <div className="page-header">
      <div className="page-block">
        <div className="row align-items-center">
          <div className="col-md-12">
            <div className="page-header-title">
              <h5 className="m-b-10">{item.title}</h5>
            </div>
            <nav aria-label="Breadcrumb">
              <ul className="breadcrumb">
                <li className="breadcrumb-item">
                  <Link to="/" aria-label="Home">
                    <FiHome aria-hidden="true" />
                  </Link>
                </li>
                {item.parentTitle && <li className="breadcrumb-item">{item.parentTitle}</li>}
                <li className="breadcrumb-item" aria-current="page">
                  {item.title}
                </li>
              </ul>
            </nav>
          </div>
        </div>
      </div>
    </div>
  );
}
