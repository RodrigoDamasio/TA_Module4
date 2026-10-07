/** Codebase names: the backend's rule (lowercase letters, digits and '-', 1-40 characters,
 * starting with a letter or digit), sent in GET /config as `codebase_id_pattern`. */

export function suggestName(folder: string): string {
  return folder
    .toLowerCase()
    .normalize("NFD")
    .replace(/[̀-ͯ]/g, "") // "São" → "sao"
    .replace(/[^a-z0-9]+/g, "-")
    .replace(/^-+|-+$/g, "")
    .slice(0, 40)
    .replace(/-+$/, "");
}

/** Why `name` can't be used, or null. `samples` are the read-only codebases. */
export function nameError(name: string, pattern: string, samples: string[]): string | null {
  if (!name) return "Give the codebase a name.";
  if (!new RegExp(pattern).test(name)) {
    return "Use 1-40 lowercase letters, digits and '-', starting with a letter or digit.";
  }
  if (samples.includes(name)) return `"${name}" is a read-only sample. Choose another name.`;
  return null;
}
