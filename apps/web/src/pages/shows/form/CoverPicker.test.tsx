import { render, screen, waitFor } from '@testing-library/react';
import userEvent from '@testing-library/user-event';
import { vi } from 'vitest';

import { coverProblem, CoverPicker, MAX_COVER_BYTES } from './CoverPicker';

const png = (name = 'cover.png') => new File(['x'], name, { type: 'image/png' });

function setup(props: Partial<React.ComponentProps<typeof CoverPicker>> = {}) {
  const onFile = vi.fn();
  const onRemove = vi.fn();
  render(<CoverPicker onFile={onFile} onRemove={onRemove} {...props} />);
  return { onFile, onRemove, input: screen.getByLabelText('Cover image (optional)') };
}

describe('coverProblem', () => {
  it('accepts PNG and JPEG up to 10 MB', () => {
    expect(coverProblem(png())).toBeNull();
    expect(coverProblem(new File(['x'], 'a.jpg', { type: 'image/jpeg' }))).toBeNull();
  });

  it('rejects other types and oversized files', () => {
    expect(coverProblem(new File(['x'], 'a.gif', { type: 'image/gif' }))).toBe(
      'Choose a PNG or JPEG image.',
    );
    const big = new File(['x'], 'big.png', { type: 'image/png' });
    Object.defineProperty(big, 'size', { value: MAX_COVER_BYTES + 1 });
    expect(coverProblem(big)).toBe('The image is larger than 10 MB.');
  });
});

describe('CoverPicker', () => {
  it('hands a valid file to the parent', async () => {
    const user = userEvent.setup();
    const { onFile, input } = setup();

    await user.upload(input, png());

    expect(onFile).toHaveBeenCalledOnce();
    expect(onFile.mock.calls[0]?.[0]).toMatchObject({ name: 'cover.png' });
  });

  it('refuses a file of the wrong type with a message instead of uploading it', async () => {
    const user = userEvent.setup({ applyAccept: false });
    const { onFile, input } = setup();

    await user.upload(input, new File(['x'], 'cover.gif', { type: 'image/gif' }));

    expect(await screen.findByRole('alert')).toHaveTextContent('Choose a PNG or JPEG image.');
    expect(onFile).not.toHaveBeenCalled();
  });

  it('shows the stored cover and offers to remove it', async () => {
    const user = userEvent.setup();
    const { onRemove } = setup({ currentUrl: '/api/shows/s1/cover?v=1' });

    expect(screen.getByRole('img', { name: 'Cover preview' })).toHaveAttribute(
      'src',
      '/api/shows/s1/cover?v=1',
    );
    await user.click(screen.getByRole('button', { name: 'Remove cover' }));

    expect(onRemove).toHaveBeenCalledOnce();
  });

  it('previews a chosen file in place of the stored cover', async () => {
    setup({ currentUrl: '/old.jpg', file: png() });

    await waitFor(() => {
      expect(screen.getByRole('img', { name: 'Cover preview' }).getAttribute('src')).toMatch(
        /^data:image\/png/,
      );
    });
  });

  it('has nothing to remove without a cover, and shows server errors', () => {
    setup({ error: 'The image is too small (400x400)' });

    expect(screen.queryByRole('button', { name: 'Remove cover' })).not.toBeInTheDocument();
    expect(screen.queryByRole('img')).not.toBeInTheDocument();
    expect(screen.getByRole('alert')).toHaveTextContent('too small');
  });

  it('disables choosing while busy', () => {
    const { input } = setup({ busy: true });

    expect(input).toBeDisabled();
  });
});
