import type { User } from '#/api/agentmesh';

import { computed, ref } from 'vue';

import { defineStore } from 'pinia';

import {
  login,
  loginWithCode,
  logout,
  me,
  registerVerified,
  resetPassword,
  sendEmailCode,
} from '#/api/agentmesh';

export const useAgentMeshAuthStore = defineStore('agentmesh-auth', () => {
  const user = ref<null | User>(null);
  const restoring = ref(false);
  const authenticated = computed(() => Boolean(user.value));

  async function restoreSession() {
    if (restoring.value) return user.value;
    restoring.value = true;
    try {
      user.value = await me();
      return user.value;
    } catch {
      user.value = null;
      return null;
    } finally {
      restoring.value = false;
    }
  }

  async function loginWithPassword(email: string, password: string) {
    user.value = await login(email, password);
    return user.value;
  }

  async function loginWithEmailCode(email: string, code: string) {
    user.value = await loginWithCode(email, code);
    return user.value;
  }

  async function registerAccount(
    email: string,
    code: string,
    password: string,
    displayName: string,
  ) {
    user.value = await registerVerified(email, code, password, displayName);
    return user.value;
  }

  async function requestEmailCode(
    email: string,
    scene: 'login' | 'register' | 'reset_password',
  ) {
    return sendEmailCode(email, scene);
  }

  async function changePassword(
    email: string,
    code: string,
    newPassword: string,
  ) {
    await resetPassword(email, code, newPassword);
  }

  async function signOut() {
    try {
      await logout();
    } finally {
      user.value = null;
    }
  }

  return {
    user,
    restoring,
    authenticated,
    restoreSession,
    loginWithPassword,
    loginWithEmailCode,
    registerAccount,
    requestEmailCode,
    changePassword,
    signOut,
  };
});
