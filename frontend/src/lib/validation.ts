/**
 * Client-side validation mirroring the backend schema rules.
 *
 * The server is still the authority; these checks just avoid a round trip and
 * give the user immediate feedback.
 */

export const NAME_MAX_LENGTH = 255;
export const SLUG_MAX_LENGTH = 100;
export const DESCRIPTION_MAX_LENGTH = 1000;

/** Same rule as the backend: lowercase alphanumeric words joined by hyphens. */
export const SLUG_PATTERN = /^[a-z0-9]+(?:-[a-z0-9]+)*$/;

export interface ResourceFormValues {
  name: string;
  slug: string;
  description: string;
}

export type FieldErrors = Partial<Record<keyof ResourceFormValues, string>>;

/** Normalise a slug the way the backend does, so the preview matches. */
export function normaliseSlug(value: string): string {
  return value.trim().toLowerCase();
}

export function validateResourceForm(values: ResourceFormValues): FieldErrors {
  const errors: FieldErrors = {};

  const name = values.name.trim();
  if (!name) {
    errors.name = 'Name is required.';
  } else if (name.length > NAME_MAX_LENGTH) {
    errors.name = `Name must be ${NAME_MAX_LENGTH} characters or fewer.`;
  }

  // Slug is optional: the backend derives one from the name when omitted.
  const slug = normaliseSlug(values.slug);
  if (slug) {
    if (slug.length > SLUG_MAX_LENGTH) {
      errors.slug = `Slug must be ${SLUG_MAX_LENGTH} characters or fewer.`;
    } else if (!SLUG_PATTERN.test(slug)) {
      errors.slug = 'Use lowercase letters, numbers and single hyphens (e.g. revenue-analytics).';
    }
  }

  if (values.description.length > DESCRIPTION_MAX_LENGTH) {
    errors.description = `Description must be ${DESCRIPTION_MAX_LENGTH} characters or fewer.`;
  }

  return errors;
}

/** Build a create/update payload, omitting blank optional fields. */
export function toResourcePayload(values: ResourceFormValues) {
  const slug = normaliseSlug(values.slug);
  const description = values.description.trim();
  return {
    name: values.name.trim(),
    ...(slug ? { slug } : {}),
    ...(description ? { description } : {}),
  };
}
