// Every dropdown is a searchable one (see components/SearchableSelect.tsx), so a long list such as
// models, voices or time zones can always be filtered by typing.
const sources = import.meta.glob<string>(['./**/*.tsx', '!./**/*.test.tsx'], {
  query: '?raw',
  import: 'default',
  eager: true,
});

describe('dropdowns', () => {
  it('uses no plain select element anywhere in the app', () => {
    const offenders = Object.entries(sources)
      .filter(([, code]) => /Form\.Select|<select[\s>]|as=["']select["']|<datalist/.test(code))
      .map(([file]) => file);

    expect(offenders).toEqual([]);
  });
});
