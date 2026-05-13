import { api } from './api.js';

export async function loadSchema() {
  const el = document.getElementById('sqlite-schema-ddl');
  if (!el) return;

  try {
    el.textContent = await api.schema();
  } catch (e) {
    el.textContent = `Unable to load SQLite schema: ${e.message}`;
  }
}
