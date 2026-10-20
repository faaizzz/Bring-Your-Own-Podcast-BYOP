import { screen, waitFor, within } from '@testing-library/react';
import userEvent from '@testing-library/user-event';

import type { Persona } from '../../lib/personas';
import { formHandlers } from '../../test/fixtures';
import { callsTo, requestBody, type Handler } from '../../test/mockApi';
import { renderApp } from '../../test/render';
import { choose } from '../../test/select';

function persona(patch: Partial<Persona> = {}): Persona {
  return {
    id: 'p1',
    name: 'Curious host',
    persona: 'Warm and well prepared.',
    tts_provider: null,
    voice_id: null,
    voice_params: {},
    ...patch,
  };
}

/** A small in-memory fake of /api/personas. */
function server(initial: Persona[] = []): Record<string, Handler> {
  let rows = initial;
  return {
    ...formHandlers(),
    'GET /api/personas': () => ({ body: rows }),
    'POST /api/personas': ({ body }) => {
      const input = body as Partial<Persona> & { name: string };
      if (rows.some((p) => p.name.toLowerCase() === input.name.toLowerCase())) {
        return {
          status: 409,
          body: { detail: `There is already a persona called '${input.name}'` },
        };
      }
      const created = persona({ id: `p${String(rows.length + 1)}`, ...input });
      rows = [...rows, created];
      return { status: 201, body: created };
    },
    'PATCH /api/personas/p1': ({ body }) => {
      rows = rows.map((p) => (p.id === 'p1' ? { ...p, ...(body as Partial<Persona>) } : p));
      return { body: rows.find((p) => p.id === 'p1') };
    },
    'DELETE /api/personas/p1': () => {
      rows = rows.filter((p) => p.id !== 'p1');
      return { status: 204 };
    },
  };
}

async function openPage(handlers: Record<string, Handler>) {
  const user = userEvent.setup();
  const rendered = await renderApp('/settings/personas', { handlers });
  await screen.findByRole('heading', { name: 'Your personas' });
  return { user, ...rendered };
}

describe('Personas page', () => {
  it('is in the sidebar under Settings', async () => {
    await openPage(server());

    expect(screen.getByRole('link', { name: 'Personas' })).toHaveAttribute(
      'href',
      '/settings/personas',
    );
  });

  it('says so when the library is empty', async () => {
    await openPage(server());

    expect(await screen.findByText(/None yet/)).toBeInTheDocument();
  });

  it('lists the personas with their default voice', async () => {
    await openPage(
      server([
        persona(),
        persona({
          id: 'p2',
          name: 'Expert analyst',
          tts_provider: 'kokoro',
          voice_id: 'af_bella',
        }),
      ]),
    );

    const expert = await screen.findByRole('article', { name: 'Expert analyst' });
    expect(within(expert).getByTestId('persona-voice')).toHaveTextContent('af_bella');
    const curious = screen.getByRole('article', { name: 'Curious host' });
    expect(within(curious).getByText('Warm and well prepared.')).toBeInTheDocument();
    expect(within(curious).queryByTestId('persona-voice')).not.toBeInTheDocument();
  });

  it('adds a persona with a default voice', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: /Add persona/ }));
    await user.click(screen.getByRole('button', { name: 'Save' }));
    expect(await screen.findByText('Enter a name')).toBeInTheDocument();
    expect(screen.getByText('Describe the persona')).toBeInTheDocument();

    await user.type(screen.getByLabelText('Name'), 'Night host');
    await user.type(screen.getByLabelText('Persona'), 'Quiet and warm.');
    await choose(user, 'Voice provider', /Kokoro/);
    await choose(user, 'Voice', /Bella/);
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('article', { name: 'Night host' })).toBeInTheDocument();
    expect(requestBody(callsTo(fetchMock, 'POST /api/personas')[0])).toMatchObject({
      name: 'Night host',
      persona: 'Quiet and warm.',
      tts_provider: 'kokoro',
      voice_id: 'af_bella',
    });
  });

  it('asks for a voice when a voice provider is chosen', async () => {
    const { user, fetchMock } = await openPage(server());

    await user.click(screen.getByRole('button', { name: /Add persona/ }));
    await user.type(screen.getByLabelText('Name'), 'Night host');
    await user.type(screen.getByLabelText('Persona'), 'Quiet.');
    await choose(user, 'Voice provider', /Kokoro/);
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(
      await screen.findByText('Choose a voice, or remove the default voice'),
    ).toBeInTheDocument();
    expect(callsTo(fetchMock, 'POST /api/personas')).toHaveLength(0);
  });

  it('shows the server’s reason when a name is taken', async () => {
    const { user } = await openPage(server([persona()]));

    await user.click(screen.getByRole('button', { name: /Add persona/ }));
    await user.type(screen.getByLabelText('Name'), 'curious host');
    await user.type(screen.getByLabelText('Persona'), 'x');
    await user.click(screen.getByRole('button', { name: 'Save' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('already a persona called');
    expect(screen.getByRole('dialog')).toBeInTheDocument();
  });

  it('edits a persona and can remove its voice', async () => {
    const { user, fetchMock } = await openPage(
      server([persona({ tts_provider: 'kokoro', voice_id: 'af_bella' })]),
    );

    await user.click(
      within(await screen.findByRole('article', { name: 'Curious host' })).getByRole('button', {
        name: 'Edit',
      }),
    );
    const text = await screen.findByLabelText('Persona');
    await user.clear(text);
    await user.type(text, 'Rewritten.');
    // The voice provider is cleared with its clear button.
    const dialog = screen.getByRole('dialog');
    await user.click(dialog.querySelector('.byop-select__clear-indicator') as HTMLElement);
    await user.click(within(dialog).getByRole('button', { name: 'Save' }));

    await waitFor(() => {
      expect(requestBody(callsTo(fetchMock, 'PATCH /api/personas/p1')[0])).toMatchObject({
        persona: 'Rewritten.',
        tts_provider: null,
        voice_id: null,
      });
    });
  });

  it('deletes a persona after a confirmation', async () => {
    const { user, fetchMock } = await openPage(server([persona()]));

    await user.click(
      within(await screen.findByRole('article', { name: 'Curious host' })).getByRole('button', {
        name: 'Delete',
      }),
    );
    expect(callsTo(fetchMock, 'DELETE /api/personas/p1')).toHaveLength(0);
    await user.click(screen.getByRole('button', { name: 'Confirm delete' }));

    await waitFor(() => {
      expect(screen.queryByRole('article', { name: 'Curious host' })).not.toBeInTheDocument();
    });
  });
});
