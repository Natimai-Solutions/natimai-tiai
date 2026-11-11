import { computed, reactive } from 'vue';
import { api } from 'boot/axios';
import { PASSWORD_MIN_LENGTH } from 'src/services/users';

/**
 * The password rules the server is configured with (PASSWORD_MIN_LENGTH,
 * PASSWORD_RESET_EXPIRE_MINUTES), read once — a deployment that changes them
 * must not find the console still saying 12 characters and one hour (audit
 * B24). The defaults stand until the answer arrives, and if it never does.
 */
const policy = reactive({ minLength: PASSWORD_MIN_LENGTH, resetExpireMinutes: 60 });
let loading: Promise<void> | null = null;

export function loadPasswordPolicy(): Promise<void> {
  loading ??= api
    .get<{ min_length: number; reset_expire_minutes: number }>('/auth/password-policy')
    .then(({ data }) => {
      policy.minLength = data.min_length;
      policy.resetExpireMinutes = data.reset_expire_minutes;
    })
    .catch(() => {
      loading = null;
    });
  return loading;
}

/** « 1 heure », « 30 minutes », « 2 heures » — the link's lifetime, in words. */
export function durationLabel(minutes: number): string {
  if (minutes % 60 === 0) {
    const h = minutes / 60;
    return h === 1 ? 'une heure' : `${h} heures`;
  }
  return `${minutes} minutes`;
}

export function usePasswordPolicy() {
  void loadPasswordPolicy();
  return {
    passwordMin: computed(() => policy.minLength),
    resetExpiry: computed(() => durationLabel(policy.resetExpireMinutes)),
  };
}
