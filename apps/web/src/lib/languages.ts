import type { SelectOption } from '../components/SearchableSelect';

// Common BCP-47 tags for podcasts. Any other well-formed tag can still be typed in.
const CODES = [
  'en',
  'en-US',
  'en-GB',
  'en-AU',
  'en-CA',
  'en-IN',
  'es',
  'es-ES',
  'es-MX',
  'es-419',
  'fr',
  'fr-FR',
  'fr-CA',
  'de',
  'de-DE',
  'de-AT',
  'de-CH',
  'it',
  'pt',
  'pt-BR',
  'pt-PT',
  'nl',
  'sv',
  'da',
  'no',
  'fi',
  'pl',
  'cs',
  'sk',
  'hu',
  'ro',
  'bg',
  'el',
  'tr',
  'ru',
  'uk',
  'he',
  'ar',
  'fa',
  'hi',
  'bn',
  'ta',
  'te',
  'ur',
  'th',
  'vi',
  'id',
  'ms',
  'fil',
  'zh',
  'zh-Hans',
  'zh-Hant',
  'zh-CN',
  'zh-TW',
  'zh-HK',
  'ja',
  'ko',
  'sw',
  'af',
  'ca',
  'hr',
  'sr',
  'sl',
  'lt',
  'lv',
  'et',
] as const; // fmt: skip

function nameOf(code: string): string {
  try {
    return new Intl.DisplayNames(['en'], { type: 'language' }).of(code) ?? code;
  } catch {
    return code;
  }
}

/** "German (de)"-style options; the search matches the name and the code. */
export function languageOptions(): SelectOption[] {
  return CODES.map((code) => ({
    value: code,
    label: `${nameOf(code)} (${code})`,
    keywords: code,
  }));
}
