import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Style } from '../../lib/styles';
import { builtInStyles } from '../../test/fixtures';
import { callsTo, requestBody, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';

function custom(patch: Partial<Style> = {}): Style {
  return {
    id: 'c1',
    kind: 'custom',
    name: 'Late-night chat',
    description: 'Slow and warm.',
    instructions: 'Keep it calm.',
    shows_using: 0,
    ...patch,
  };
}

/** A small in-memory fake of /api/styles. */
function server(initial: Style[] = [], refuseDelete?: string) {
  let mine = initial;
  const handlers: Record<string, Handler> = {
    'GET /api/styles': () => ({ body: [...builtInStyles, ...mine] }),
    'POST /api/styles': ({ body }) => {
      const input = body as { name: string; description: string; instructions: string };
      if (mine.some((s) => s.name.toLowerCase() === input.name.toLowerCase())) {
        return { status: 409, body: { detail: `There is already a style called '${input.name}'` } };
      }
      const created = custom({ id: `c${String(mine.length + 1)}`, ...input });
      mine = [...mine, created];
      return { status: 201, body: created };
    },
    'PATCH /api/styles/c1': ({ body }) => {
      mine = mine.map((s) => (s.id === 'c1' ? { ...s, ...(body as Partial<Style>) } : s));
      return { body: mine.find((s) => s.id === 'c1') };
    },
    'DELETE /api/styles/c1': () => {
      if (refuseDelete) return { status: 409, body: { detail: refuseDelete } };
      mine = mine.filter((s) => s.id !== 'c1');
      return { status: 204 };
    },
  };
  return handlers;
}

async function openPage(handlers: Record<string, Handler>) {
  const user = userEvent.setup();
  const rendered = await renderApp('/settings/styles', { handlers });
  await screen.findByRole('heading', { name: 'Built-in styles' });
  return { user, ...rendered };
}

const card = (name: string) => screen.getByRole('article', { name });

describe('Styles page', () => {
  it('is in the sidebar under Settings', async () => {
    await openPage(server());

    expect(screen.getByRole('link', { name: 'Styles' })).toHaveAttribute(
      'href',
      '/settings/styles',
    );
  });

  it('lists the built-in styles and shows exactly what they tell the model', async () => {
    const { user } = await openPage(server());

    expect(screen.getAllByRole('article')).toHaveLength(4);
    expect(within(card('Conversational')).getByText('Built-in')).toBeInTheDocument();
    expect(within(card('Conversational')).queryByRole('button', { name: 'Edit' })).toBeNull();
    expect(within(card('Conversational')).queryByRole('button', { name: 'Delete' })).toBeNull();
    expect(screen.queryByTestId('instructions')).not.toBeInTheDocument();

    await user.click(
      within(card('Conversational')).getByRole('button', { name: 'View instructions' }),
    );

    expect(within(card('Conversational')).getByTestId('instructions')).toHaveTextContent(
      'The episode feels like friends talking.',
    );
    expect(
      await screen.findByText(
        'None yet. Add one, or duplicate a built-in style below and change it.',
      ),
    ).toBeInTheDocument();
  });

  it('duplicates a built-in style into an editable custom one', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(within(card('Interview')).getByRole('button', { name: 'Duplicate' }));
    const dialog = await screen.findByRole('dialog');
    expect(within(dialog).getByLabelText('Name')).toHaveValue('Interview (copy)');
    // The copy carries the instructions as they are, ready to edit.
    expect(within(dialog).getByLabelText('Instructions')).toHaveValue(
      '{{ speakers[0].name }} is the interviewer.',
    );
    await user.clear(within(dialog).getByLabelText('Name'));
    await user.type(within(dialog).getByLabelText('Name'), 'My interview');
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    const mine = await screen.findByRole('article', { name: 'My interview' });
    expect(within(mine).getByText('Custom')).toBeInTheDocument();
    expect(within(mine).getByRole('button', { name: 'Edit' })).toBeInTheDocument();
    expect(requestBody(callsTo(fetchMock, 'POST /api/styles')[0])).toMatchObject({
      name: 'My interview',
      instructions: '{{ speakers[0].name }} is the interviewer.',
    });
  });

  it('names a copy so that it does not clash with an earlier one', async () => {
    const { user } = await openPage(server([custom({ id: 'c9', name: 'Interview (copy)' })]));

    await user.click(within(card('Interview')).getByRole('button', { name: 'Duplicate' }));

    expect(await screen.findByLabelText('Name')).toHaveValue('Interview (copy 2)');
  });

  it('adds a style from scratch and checks the form first', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: /Add style/ }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Enter a name')).toBeInTheDocument();
    expect(screen.getByText('Describe how the episode should be told')).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/styles')).toHaveLength(0);

    await user.type(screen.getByLabelText('Name'), 'Late-night chat');
    await user.type(screen.getByLabelText('Instructions'), 'Keep it calm.');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('article', { name: 'Late-night chat' })).toBeInTheDocument();
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('shows the server’s reason when a style cannot be saved', async () => {
    const { user } = await openPage(server([custom()]));

    await user.click(screen.getByRole('button', { name: /Add style/ }));
    await user.type(screen.getByLabelText('Name'), 'late-night chat');
    await user.type(screen.getByLabelText('Instructions'), 'x');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already a style called');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('edits a custom style', async () => {
    const { user, fetchMock } = await openPage(server([custom()]));

    await user.click(within(card('Late-night chat')).getByRole('button', { name: 'Edit' }));
    const field = await screen.findByLabelText('Instructions');
    expect(field).toHaveValue('Keep it calm.');
    await user.clear(field);
    await user.type(field, 'Whisper.');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(requestBody(callsTo(fetchMock, 'PATCH /api/styles/c1')[0])).toMatchObject({
        instructions: 'Whisper.',
      });
    });
    expect(screen.queryByRole('dialog')).not.toBeInTheDocument();
  });

  it('deletes a style after a confirmation', async () => {
    const { user, fetchMock } = await openPage(server([custom()]));

    await user.click(within(card('Late-night chat')).getByRole('button', { name: 'Delete' }));
    expect(callsTo(fetchMock, 'DELETE /api/styles/c1')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('article', { name: 'Late-night chat' })).not.toBeInTheDocument();
    });
  });

  it('says why a style in use cannot be deleted', async () => {
    const { user } = await openPage(
      server(
        [custom({ shows_using: 2 })],
        "The style 'Late-night chat' is used by 2 show(s): 'Alpha', 'Beta'. Choose another style for them first.",
      ),
    );

    expect(within(card('Late-night chat')).getByText('Used by 2 shows')).toBeInTheDocument();
    await user.click(within(card('Late-night chat')).getByRole('button', { name: 'Delete' }));
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    expect(await screen.findByText(/used by 2 show\(s\): 'Alpha', 'Beta'/)).toBeInTheDocument();
    expect(screen.getByRole('article', { name: 'Late-night chat' })).toBeInTheDocument();
  });
});
