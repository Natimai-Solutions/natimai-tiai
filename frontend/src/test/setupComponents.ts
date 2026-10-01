import { vi } from 'vitest';
import { installQuasarPlugin } from './quasar';

// Every component spec mounts Quasar components: install the framework once
// here rather than at the top of each file, where it could be forgotten.
installQuasarPlugin();

// A component reaches the server through a service, and every service through
// the app's axios instance — whose boot file needs the Quasar CLI's `#q-app`,
// which only exists inside a Quasar build. A component spec talks to no
// server: the instance is a stub whose calls fail loudly, and a spec that
// wants an answer mocks the service it needs.
vi.mock('boot/axios', () => {
  const offline = () => Promise.reject(new Error('Pas de serveur dans un test de composant'));
  return { api: { get: offline, post: offline, put: offline, patch: offline, delete: offline } };
});
