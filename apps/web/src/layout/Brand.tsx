import { FiMic } from 'react-icons/fi';
import { Link } from 'react-router-dom';

export function Brand(): React.JSX.Element {
  return (
    <Link to="/" className="b-brand" aria-label="BYOP home">
      <span className="b-bg">
        <FiMic aria-hidden="true" />
      </span>
      <span className="b-title">BYOP</span>
    </Link>
  );
}
