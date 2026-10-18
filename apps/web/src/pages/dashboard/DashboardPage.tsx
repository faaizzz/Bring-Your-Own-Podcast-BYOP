import { Card, Col, Row } from 'react-bootstrap';

import { MainCard } from '../../layout/MainCard';

const stats = [
  { title: 'Shows', className: 'bg-c-blue', caption: 'Active shows' },
  { title: 'Episodes', className: 'bg-c-green', caption: 'Published' },
  { title: 'To review', className: 'bg-c-yellow', caption: 'Drafts waiting' },
  { title: 'This month', className: 'bg-c-red', caption: 'Estimated cost' },
];

export default function DashboardPage(): React.JSX.Element {
  return (
    <>
      <Row>
        {stats.map((stat) => (
          <Col key={stat.title} md={6} xl={3}>
            <Card className={`${stat.className} order-card`}>
              <Card.Body>
                <h6 className="text-white">{stat.title}</h6>
                <h2 className="text-end text-white">
                  <span>-</span>
                </h2>
                <p className="mb-0">{stat.caption}</p>
              </Card.Body>
            </Card>
          </Col>
        ))}
      </Row>
      <Row>
        <Col xs={12}>
          <MainCard title="Welcome to BYOP">
            <p className="mb-0">
              Your shows, episodes and costs will appear here as soon as you create your first show.
            </p>
          </MainCard>
        </Col>
      </Row>
    </>
  );
}
