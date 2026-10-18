from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession


async def test_writes_are_visible_inside_the_test(db_session: AsyncSession) -> None:
    await db_session.execute(text("CREATE TABLE rollback_probe (id int)"))
    await db_session.execute(text("INSERT INTO rollback_probe VALUES (1)"))
    await db_session.commit()
    count = await db_session.scalar(text("SELECT count(*) FROM rollback_probe"))
    assert count == 1


async def test_previous_test_writes_were_rolled_back(db_session: AsyncSession) -> None:
    # Runs after the test above (file order); its table must be gone.
    assert await db_session.scalar(text("SELECT to_regclass('rollback_probe')")) is None
