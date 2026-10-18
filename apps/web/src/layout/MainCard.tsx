import { Card } from 'react-bootstrap';

type MainCardProps = {
  title: string;
  children: React.ReactNode;
};

export function MainCard({ title, children }: MainCardProps): React.JSX.Element {
  return (
    <Card>
      <Card.Header>
        <Card.Title as="h5">{title}</Card.Title>
      </Card.Header>
      <Card.Body>{children}</Card.Body>
    </Card>
  );
}
